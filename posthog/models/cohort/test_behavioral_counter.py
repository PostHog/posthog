"""
Tests for Behavioral Counter System

This module contains comprehensive tests for the real-time behavioral
cohort counting system implementation.
"""

import json
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import pytest
from django.test import TestCase
from django.utils import timezone
from freezegun import freeze_time

from posthog.models.cohort.behavioral_counter import (
    BehavioralCounter,
    BehavioralCounterError,
    BehavioralCounterManager,
)
from posthog.models.cohort.cohort import Cohort
from posthog.models.cohort.real_time_evaluation import RealTimeCohortEvaluator, RealTimeCohortService
from posthog.models.team.team import Team
from posthog.models.person.person import Person
from posthog.cdp.behavioral_cohort_processor import BehavioralCohortProcessor
from posthog.test.base import BaseTest


class TestBehavioralCounterManager(BaseTest):
    """Test the BehavioralCounterManager class."""
    
    def setUp(self):
        super().setUp()
        self.manager = BehavioralCounterManager()
        self.test_filters = {
            "properties": {
                "type": "OR",
                "values": [{
                    "key": "test_event",
                    "type": "behavioral",
                    "value": "performed_event",
                    "operator_value": 5,
                    "time_value": 7,
                    "time_interval": "day"
                }]
            }
        }
    
    @patch('posthog.models.cohort.behavioral_counter.get_client')
    def test_compile_and_cache_filters(self, mock_get_client):
        """Test filter compilation and caching."""
        mock_redis = Mock()
        mock_get_client.return_value = mock_redis
        mock_redis.get.return_value = None
        
        # Test compilation
        filter_hash = self.manager.compile_and_cache_filters(self.team.id, self.test_filters)
        
        # Should return a hash
        self.assertIsInstance(filter_hash, str)
        self.assertEqual(len(filter_hash), 16)
        
        # Should cache bytecode
        mock_redis.setex.assert_called()
        
        # Test cache hit
        mock_redis.get.return_value = b"cached_bytecode"
        filter_hash2 = self.manager.compile_and_cache_filters(self.team.id, self.test_filters)
        
        # Should return same hash
        self.assertEqual(filter_hash, filter_hash2)
    
    @patch('posthog.models.cohort.behavioral_counter.get_client')
    def test_increment_counter(self, mock_get_client):
        """Test counter increment functionality."""
        mock_redis = Mock()
        mock_get_client.return_value = mock_redis
        mock_redis.pipeline.return_value = mock_redis
        mock_redis.execute.return_value = [5]
        
        # Test increment
        result = self.manager.increment_counter(
            self.team.id,
            "test_hash",
            123,
            datetime(2023, 1, 15),
            2
        )
        
        # Should return incremented value
        self.assertEqual(result, 5)
        
        # Should call Redis operations
        mock_redis.incr.assert_called_once_with(
            "behavioral_counter:2:test_hash:123:2023-01-15", 2
        )
        mock_redis.expire.assert_called_once()
    
    @patch('posthog.models.cohort.behavioral_counter.get_client')
    def test_get_counter_value(self, mock_get_client):
        """Test getting counter values."""
        mock_redis = Mock()
        mock_get_client.return_value = mock_redis
        mock_redis.get.return_value = b"42"
        
        # Test getting value
        result = self.manager.get_counter_value(
            self.team.id,
            "test_hash",
            123,
            datetime(2023, 1, 15)
        )
        
        self.assertEqual(result, 42)
        
        # Test missing value
        mock_redis.get.return_value = None
        result = self.manager.get_counter_value(
            self.team.id,
            "test_hash",
            123,
            datetime(2023, 1, 15)
        )
        
        self.assertEqual(result, 0)
    
    @patch('posthog.models.cohort.behavioral_counter.get_client')
    def test_get_aggregated_count(self, mock_get_client):
        """Test aggregated count across date range."""
        mock_redis = Mock()
        mock_get_client.return_value = mock_redis
        mock_redis.pipeline.return_value = mock_redis
        mock_redis.execute.return_value = [b"5", b"3", None, b"2"]
        
        # Test aggregation
        result = self.manager.get_aggregated_count(
            self.team.id,
            "test_hash",
            123,
            datetime(2023, 1, 15),
            datetime(2023, 1, 18)
        )
        
        # Should sum non-None values: 5 + 3 + 2 = 10
        self.assertEqual(result, 10)
        
        # Should query 4 days
        self.assertEqual(mock_redis.get.call_count, 4)
    
    @patch('posthog.models.cohort.behavioral_counter.get_client')
    def test_get_person_daily_counts(self, mock_get_client):
        """Test getting daily counts for a person."""
        mock_redis = Mock()
        mock_get_client.return_value = mock_redis
        mock_redis.pipeline.return_value = mock_redis
        mock_redis.execute.return_value = [b"1", b"2", b"0", None]
        
        with freeze_time("2023-01-18"):
            result = self.manager.get_person_daily_counts(
                self.team.id,
                "test_hash",
                123,
                4
            )
        
        # Should return list of (date, count) tuples
        self.assertEqual(len(result), 4)
        self.assertEqual(result[0][1], 1)  # First day count
        self.assertEqual(result[1][1], 2)  # Second day count
        self.assertEqual(result[2][1], 0)  # Third day count
        self.assertEqual(result[3][1], 0)  # Fourth day count (None -> 0)


class TestBehavioralCounter(BaseTest):
    """Test the BehavioralCounter class."""
    
    def setUp(self):
        super().setUp()
        self.cohort = Cohort.objects.create(
            team=self.team,
            name="Test Behavioral Cohort",
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{
                        "key": "test_event",
                        "type": "behavioral",
                        "value": "performed_event",
                        "operator_value": 5,
                        "time_value": 7,
                        "time_interval": "day"
                    }]
                }
            }
        )
        self.person = Person.objects.create(team=self.team, distinct_ids=["test_user"])
    
    @patch('posthog.models.cohort.behavioral_counter.BehavioralCounterManager')
    def test_behavioral_counter_init(self, mock_manager_class):
        """Test BehavioralCounter initialization."""
        mock_manager = Mock()
        mock_manager_class.return_value = mock_manager
        mock_manager.compile_and_cache_filters.return_value = "test_hash"
        
        counter = BehavioralCounter(self.team.id, self.cohort)
        
        # Should compile filters on first access
        filter_hash = counter.filter_hash
        self.assertEqual(filter_hash, "test_hash")
        
        # Should cache the hash
        filter_hash2 = counter.filter_hash
        self.assertEqual(filter_hash2, "test_hash")
        
        # Should only compile once
        mock_manager.compile_and_cache_filters.assert_called_once()
    
    @patch('posthog.models.cohort.behavioral_counter.BehavioralCounterManager')
    def test_increment_for_person(self, mock_manager_class):
        """Test incrementing counter for a person."""
        mock_manager = Mock()
        mock_manager_class.return_value = mock_manager
        mock_manager.compile_and_cache_filters.return_value = "test_hash"
        mock_manager.increment_counter.return_value = 5
        
        counter = BehavioralCounter(self.team.id, self.cohort)
        
        # Test increment
        result = counter.increment_for_person(self.person.id, datetime(2023, 1, 15))
        
        self.assertEqual(result, 5)
        mock_manager.increment_counter.assert_called_once_with(
            self.team.id, "test_hash", self.person.id, datetime(2023, 1, 15), 1
        )
    
    @patch('posthog.models.cohort.behavioral_counter.BehavioralCounterManager')
    def test_get_person_count(self, mock_manager_class):
        """Test getting person count."""
        mock_manager = Mock()
        mock_manager_class.return_value = mock_manager
        mock_manager.compile_and_cache_filters.return_value = "test_hash"
        mock_manager.get_aggregated_count.return_value = 10
        
        counter = BehavioralCounter(self.team.id, self.cohort)
        
        # Test get count
        with freeze_time("2023-01-15"):
            result = counter.get_person_count(self.person.id, 7)
        
        self.assertEqual(result, 10)
        mock_manager.get_aggregated_count.assert_called_once()
    
    @patch('posthog.models.cohort.behavioral_counter.BehavioralCounterManager')
    def test_matches_threshold(self, mock_manager_class):
        """Test threshold matching."""
        mock_manager = Mock()
        mock_manager_class.return_value = mock_manager
        mock_manager.compile_and_cache_filters.return_value = "test_hash"
        mock_manager.get_aggregated_count.return_value = 10
        
        counter = BehavioralCounter(self.team.id, self.cohort)
        
        # Test above threshold
        result = counter.matches_threshold(self.person.id, 5, 7)
        self.assertTrue(result)
        
        # Test below threshold
        result = counter.matches_threshold(self.person.id, 15, 7)
        self.assertFalse(result)


class TestRealTimeCohortEvaluator(BaseTest):
    """Test the RealTimeCohortEvaluator class."""
    
    def setUp(self):
        super().setUp()
        self.evaluator = RealTimeCohortEvaluator()
        self.cohort = Cohort.objects.create(
            team=self.team,
            name="Test Behavioral Cohort",
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{
                        "key": "test_event",
                        "type": "behavioral",
                        "value": "performed_event",
                        "operator_value": 5,
                        "time_value": 7,
                        "time_interval": "day"
                    }]
                }
            }
        )
        self.person = Person.objects.create(team=self.team, distinct_ids=["test_user"])
    
    def test_parse_behavioral_filters(self):
        """Test parsing behavioral filters."""
        # Test valid filters
        criteria = self.evaluator._parse_behavioral_filters(self.cohort.filters)
        self.assertEqual(len(criteria), 1)
        self.assertEqual(criteria[0]["type"], "behavioral")
        self.assertEqual(criteria[0]["value"], "performed_event")
        
        # Test empty filters
        criteria = self.evaluator._parse_behavioral_filters({})
        self.assertEqual(len(criteria), 0)
        
        # Test non-behavioral filters
        filters = {
            "properties": {
                "type": "OR",
                "values": [{
                    "key": "test_prop",
                    "type": "person",
                    "value": "test_value"
                }]
            }
        }
        criteria = self.evaluator._parse_behavioral_filters(filters)
        self.assertEqual(len(criteria), 0)
    
    @patch('posthog.models.cohort.behavioral_counter.BehavioralCounter')
    def test_evaluate_performed_event(self, mock_counter_class):
        """Test evaluating performed_event criterion."""
        mock_counter = Mock()
        mock_counter_class.return_value = mock_counter
        mock_counter.get_person_count.return_value = 10
        
        # Test above threshold
        result = self.evaluator._evaluate_performed_event(
            mock_counter, self.person.id, 5, 7
        )
        self.assertTrue(result)
        
        # Test below threshold
        mock_counter.get_person_count.return_value = 3
        result = self.evaluator._evaluate_performed_event(
            mock_counter, self.person.id, 5, 7
        )
        self.assertFalse(result)
    
    @patch('posthog.models.cohort.behavioral_counter.BehavioralCounter')
    def test_evaluate_performed_event_regularly(self, mock_counter_class):
        """Test evaluating performed_event_regularly criterion."""
        mock_counter = Mock()
        mock_counter_class.return_value = mock_counter
        
        # Mock daily counts with regular activity
        daily_counts = [
            (datetime(2023, 1, 10), 1),
            (datetime(2023, 1, 11), 2),
            (datetime(2023, 1, 12), 0),
            (datetime(2023, 1, 13), 1),
            (datetime(2023, 1, 14), 3),
            (datetime(2023, 1, 15), 0),
            (datetime(2023, 1, 16), 1),
        ]
        mock_counter.manager.get_person_daily_counts.return_value = daily_counts
        
        # Test regular activity (5 out of 7 days)
        result = self.evaluator._evaluate_performed_event_regularly(
            mock_counter, self.person.id, 5, 7
        )
        self.assertTrue(result)  # 5 active days >= 3.5 required days
        
        # Test irregular activity
        daily_counts = [
            (datetime(2023, 1, 10), 1),
            (datetime(2023, 1, 11), 0),
            (datetime(2023, 1, 12), 0),
            (datetime(2023, 1, 13), 0),
            (datetime(2023, 1, 14), 0),
            (datetime(2023, 1, 15), 0),
            (datetime(2023, 1, 16), 0),
        ]
        mock_counter.manager.get_person_daily_counts.return_value = daily_counts
        
        result = self.evaluator._evaluate_performed_event_regularly(
            mock_counter, self.person.id, 5, 7
        )
        self.assertFalse(result)  # 1 active day < 3.5 required days
    
    @patch('posthog.models.cohort.behavioral_counter.BehavioralCounter')
    def test_evaluate_cohort_for_person(self, mock_counter_class):
        """Test full cohort evaluation for a person."""
        mock_counter = Mock()
        mock_counter_class.return_value = mock_counter
        mock_counter.get_person_count.return_value = 10
        
        # Test successful evaluation
        result = self.evaluator.evaluate_cohort_for_person(
            self.cohort, self.person.id
        )
        self.assertTrue(result)
        
        # Test failed evaluation
        mock_counter.get_person_count.return_value = 3
        result = self.evaluator.evaluate_cohort_for_person(
            self.cohort, self.person.id
        )
        self.assertFalse(result)
    
    @patch('posthog.models.cohort.behavioral_counter.BehavioralCounter')
    def test_evaluate_cohort_batch(self, mock_counter_class):
        """Test batch cohort evaluation."""
        mock_counter = Mock()
        mock_counter_class.return_value = mock_counter
        
        # Mock different results for different persons
        def mock_get_person_count(person_id, days):
            if person_id == 1:
                return 10  # Above threshold
            elif person_id == 2:
                return 3   # Below threshold
            else:
                return 0
        
        mock_counter.get_person_count.side_effect = mock_get_person_count
        
        # Test batch evaluation
        results = self.evaluator.evaluate_cohort_batch(
            self.cohort, [1, 2, 3]
        )
        
        self.assertEqual(len(results), 3)
        self.assertTrue(results[1])   # Person 1 above threshold
        self.assertFalse(results[2])  # Person 2 below threshold
        self.assertFalse(results[3])  # Person 3 no activity


class TestBehavioralCohortProcessor(BaseTest):
    """Test the BehavioralCohortProcessor class."""
    
    def setUp(self):
        super().setUp()
        self.processor = BehavioralCohortProcessor()
        self.cohort = Cohort.objects.create(
            team=self.team,
            name="Test Behavioral Cohort",
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{
                        "key": "test_event",
                        "type": "behavioral",
                        "value": "performed_event",
                        "operator_value": 5,
                        "time_value": 7,
                        "time_interval": "day"
                    }]
                }
            }
        )
        self.person = Person.objects.create(team=self.team, distinct_ids=["test_user"])
    
    def test_is_behavioral_cohort(self):
        """Test identifying behavioral cohorts."""
        # Test behavioral cohort
        result = self.processor._is_behavioral_cohort(self.cohort)
        self.assertTrue(result)
        
        # Test non-behavioral cohort
        static_cohort = Cohort.objects.create(
            team=self.team,
            name="Static Cohort",
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{
                        "key": "test_prop",
                        "type": "person",
                        "value": "test_value"
                    }]
                }
            }
        )
        result = self.processor._is_behavioral_cohort(static_cohort)
        self.assertFalse(result)
    
    @patch('posthog.models.cohort.behavioral_counter.BehavioralCounterManager')
    def test_process_event(self, mock_counter_manager_class):
        """Test processing a single event."""
        mock_manager = Mock()
        mock_counter_manager_class.return_value = mock_manager
        mock_manager.compile_and_cache_filters.return_value = "test_hash"
        mock_manager.get_cached_bytecode.return_value = b"test_bytecode"
        
        # Mock person resolution
        with patch.object(self.processor, '_resolve_person_id') as mock_resolve:
            mock_resolve.return_value = self.person.id
            
            # Mock team lookup
            with patch.object(self.processor, '_get_team') as mock_get_team:
                mock_get_team.return_value = self.team
                
                # Mock cohort lookup
                with patch.object(self.processor, '_get_active_behavioral_cohorts') as mock_get_cohorts:
                    mock_get_cohorts.return_value = [self.cohort]
                    
                    # Mock bytecode execution
                    with patch('posthog.cdp.behavioral_cohort_processor.execute_bytecode') as mock_execute:
                        mock_execute.return_value = True
                        
                        # Test event processing
                        event_data = {
                            "team_id": self.team.id,
                            "distinct_id": "test_user",
                            "event": "test_event",
                            "timestamp": "2023-01-15T10:00:00Z",
                            "properties": {}
                        }
                        
                        self.processor.process_event(event_data)
                        
                        # Should increment counter
                        mock_manager.increment_counter.assert_called_once()
    
    def test_process_batch(self):
        """Test processing a batch of events."""
        events = [
            {
                "team_id": self.team.id,
                "distinct_id": "user1",
                "event": "test_event",
                "timestamp": "2023-01-15T10:00:00Z",
                "properties": {}
            },
            {
                "team_id": self.team.id,
                "distinct_id": "user2", 
                "event": "test_event",
                "timestamp": "2023-01-15T11:00:00Z",
                "properties": {}
            }
        ]
        
        with patch.object(self.processor, 'process_event') as mock_process:
            self.processor.process_batch(events)
            
            # Should process each event
            self.assertEqual(mock_process.call_count, 2)


class TestRealTimeCohortService(BaseTest):
    """Test the RealTimeCohortService class."""
    
    def setUp(self):
        super().setUp()
        self.service = RealTimeCohortService()
        self.cohort = Cohort.objects.create(
            team=self.team,
            name="Test Behavioral Cohort",
            filters={
                "properties": {
                    "type": "OR", 
                    "values": [{
                        "key": "test_event",
                        "type": "behavioral",
                        "value": "performed_event",
                        "operator_value": 5,
                        "time_value": 7,
                        "time_interval": "day"
                    }]
                }
            }
        )
        self.person = Person.objects.create(team=self.team, distinct_ids=["test_user"])
    
    @patch('posthog.models.cohort.real_time_evaluation.RealTimeCohortEvaluator')
    def test_is_person_in_cohort(self, mock_evaluator_class):
        """Test checking if person is in cohort."""
        mock_evaluator = Mock()
        mock_evaluator_class.return_value = mock_evaluator
        mock_evaluator.evaluate_cohort_for_person.return_value = True
        
        # Test person in cohort
        result = self.service.is_person_in_cohort(self.cohort.id, self.person.id)
        self.assertTrue(result)
        
        # Test person not in cohort
        mock_evaluator.evaluate_cohort_for_person.return_value = False
        result = self.service.is_person_in_cohort(self.cohort.id, self.person.id)
        self.assertFalse(result)
        
        # Test non-existent cohort
        result = self.service.is_person_in_cohort(99999, self.person.id)
        self.assertFalse(result)
    
    @patch('posthog.models.cohort.behavioral_counter.BehavioralCounter')
    def test_invalidate_cohort_cache(self, mock_counter_class):
        """Test cache invalidation."""
        mock_counter = Mock()
        mock_counter_class.return_value = mock_counter
        
        # Test cache invalidation
        self.service.invalidate_cohort_cache(self.cohort.id)
        
        mock_counter.invalidate_cache.assert_called_once()
        
        # Test non-existent cohort
        self.service.invalidate_cohort_cache(99999)  # Should not raise exception


@pytest.mark.django_db
class TestIntegration:
    """Integration tests for the behavioral counter system."""
    
    def test_end_to_end_workflow(self):
        """Test complete end-to-end workflow."""
        # This would test the complete workflow from event ingestion
        # to cohort evaluation using real Redis and database
        pass
    
    def test_performance_with_large_datasets(self):
        """Test performance with large datasets."""
        # This would test performance characteristics
        # with large numbers of events and persons
        pass
    
    def test_error_handling_and_recovery(self):
        """Test error handling and recovery scenarios."""
        # This would test various error scenarios
        # and recovery mechanisms
        pass