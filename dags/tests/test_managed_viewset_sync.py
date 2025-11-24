import pytest
from unittest.mock import patch

from dagster import build_op_context

from posthog.models import Organization, Team

from products.data_warehouse.backend.models.datawarehouse_managed_viewset import DataWarehouseManagedViewSet
from products.data_warehouse.backend.types import DataWarehouseManagedViewSetKind

from dags.managed_viewset_sync import sync_managed_viewsets_job, sync_managed_viewsets_op


class TestSyncManagedViewsetsOp:
    @pytest.mark.django_db
    def test_sync_all_viewsets_success(self):
        # Setup - create real database objects
        org = Organization.objects.create(name="Test Org")
        team1 = Team.objects.create(organization=org, name="Test Team 1")
        team2 = Team.objects.create(organization=org, name="Test Team 2")

        # Create real ManagedViewsets
        DataWarehouseManagedViewSet.objects.create(team=team1, kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS)
        DataWarehouseManagedViewSet.objects.create(team=team2, kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS)

        # Mock the sync_views method to avoid actual database operations
        with patch.object(DataWarehouseManagedViewSet, "sync_views") as mock_sync:
            # Create proper Dagster context
            context = build_op_context(op_config={"kind": ""})

            # Execute
            sync_managed_viewsets_op(context)

            # Verify
            assert mock_sync.call_count == 2

            # Check metadata
            metadata = context.get_output_metadata("result")
            assert metadata["total_viewsets"].value == 2  # type: ignore
            assert metadata["synced_count"].value == 2  # type: ignore
            assert metadata["failed_count"].value == 0  # type: ignore

    @pytest.mark.django_db
    def test_sync_filtered_by_kind(self):
        # Setup - create real database objects
        org = Organization.objects.create(name="Test Org")
        team1 = Team.objects.create(organization=org, name="Test Team 1")
        team2 = Team.objects.create(organization=org, name="Test Team 2")

        # Create real ManagedViewsets
        DataWarehouseManagedViewSet.objects.create(team=team1, kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS)
        DataWarehouseManagedViewSet.objects.create(team=team2, kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS)

        # Mock the sync_views method
        with patch.object(DataWarehouseManagedViewSet, "sync_views") as mock_sync:
            # Create proper Dagster context
            context = build_op_context(op_config={"kind": "revenue_analytics"})

            # Execute
            sync_managed_viewsets_op(context)

            # Verify
            assert mock_sync.call_count == 2

            # Check metadata
            metadata = context.get_output_metadata("result")
            assert metadata["total_viewsets"].value == 2  # type: ignore
            assert metadata["synced_count"].value == 2  # type: ignore
            assert metadata["failed_count"].value == 0  # type: ignore

    @pytest.mark.django_db
    def test_sync_with_failures(self):
        # Setup - create real database objects
        org = Organization.objects.create(name="Test Org")
        team1 = Team.objects.create(organization=org, name="Test Team 1")
        team2 = Team.objects.create(organization=org, name="Test Team 2")

        # Create real ManagedViewsets
        DataWarehouseManagedViewSet.objects.create(team=team1, kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS)
        DataWarehouseManagedViewSet.objects.create(team=team2, kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS)

        # Mock sync_views to fail for one viewset
        called = False

        def mock_sync_views():
            nonlocal called
            # Fail for the second viewset (team2)
            if called:
                raise Exception("Sync failed")
            called = True
            return None

        with patch.object(DataWarehouseManagedViewSet, "sync_views", side_effect=mock_sync_views):
            # Create proper Dagster context
            context = build_op_context(op_config={"kind": ""})

            # Execute and expect failure
            with pytest.raises(Exception, match="Failed to sync 1 out of 2 viewsets"):
                sync_managed_viewsets_op(context)

    @pytest.mark.django_db
    def test_sync_with_invalid_kind(self):
        # Create proper Dagster context
        context = build_op_context(op_config={"kind": "invalid_kind"})

        # Execute and verify exception
        with pytest.raises(ValueError, match="Invalid kind: invalid_kind"):
            sync_managed_viewsets_op(context)


class TestSyncManagedViewsetsJob:
    @pytest.mark.django_db
    def test_job_execution_success(self):
        # Setup - create real database objects
        org = Organization.objects.create(name="Test Org")
        team = Team.objects.create(organization=org, name="Test Team")

        # Create real ManagedViewset
        DataWarehouseManagedViewSet.objects.create(team=team, kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS)

        # Mock the sync_views method
        with patch.object(DataWarehouseManagedViewSet, "sync_views") as mock_sync:
            # Execute job
            result = sync_managed_viewsets_job.execute_in_process(
                run_config={"ops": {"sync_managed_viewsets_op": {"config": {"kind": "revenue_analytics"}}}}
            )

            # Verify
            assert result.success
            mock_sync.assert_called_once()
