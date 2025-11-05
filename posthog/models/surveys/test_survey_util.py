from unittest import TestCase

from posthog.models.surveys.util import (
    _build_coalesce_query,
    _build_id_based_key,
    _build_index_based_key,
    get_survey_response_clickhouse_query,
)


class TestSurveyResponseFunctions(TestCase):
    def test_build_id_based_key_with_question_id(self):
        """Test building an ID-based key when a question ID is provided"""
        key = _build_id_based_key(0, "question123")
        self.assertEqual(key, "'$survey_response_question123'")

    def test_build_id_based_key_without_question_id(self):
        """Test building an ID-based key when no question ID is provided"""
        key = _build_id_based_key(2, None)
        self.assertEqual(
            key,
            "CONCAT('$survey_response_', JSONExtractString(JSONExtractArrayRaw(properties, '$survey_questions')[3], 'id'))",
        )

    def test_build_index_based_key_for_first_question(self):
        """Test building an index-based key for the first question"""
        key = _build_index_based_key(0)
        self.assertEqual(key, "$survey_response")

    def test_build_index_based_key_for_other_questions(self):
        """Test building an index-based key for non-first questions"""
        key = _build_index_based_key(3)
        self.assertEqual(key, "$survey_response_3")

    def test_build_coalesce_query(self):
        """Test building the final coalesce query"""
        query = _build_coalesce_query("'$survey_response_abc123'", "$survey_response_2")
        expected = """COALESCE(
        NULLIF(JSONExtractString(properties, '$survey_response_abc123'), ''),
        NULLIF(JSONExtractString(properties, '$survey_response_2'), '')
    )"""
        self.assertEqual(query, expected)

    def test_get_survey_response_clickhouse_query_with_question_id(self):
        """Test the full query generation with a specific question ID"""
        query = get_survey_response_clickhouse_query(1, "abc123")
        expected = """COALESCE(
        NULLIF(JSONExtractString(properties, '$survey_response_abc123'), ''),
        NULLIF(JSONExtractString(properties, '$survey_response_1'), '')
    )"""
        self.assertEqual(query, expected)

    def test_get_survey_response_clickhouse_query_without_question_id(self):
        """Test the full query generation with just a question index"""
        query = get_survey_response_clickhouse_query(0)
        expected = """COALESCE(
        NULLIF(JSONExtractString(properties, CONCAT('$survey_response_', JSONExtractString(JSONExtractArrayRaw(properties, '$survey_questions')[1], 'id'))), ''),
        NULLIF(JSONExtractString(properties, '$survey_response'), '')
    )"""
        self.assertEqual(query, expected)

    def test_get_survey_response_clickhouse_query_multiple_choice(self):
        """Test the full query generation with a multiple choice question"""
        query = get_survey_response_clickhouse_query(1, "abc123", True)
        expected = """if(
        JSONHas(properties, '$survey_response_abc123') AND length(JSONExtractArrayRaw(properties, '$survey_response_abc123')) > 0,
        JSONExtractArrayRaw(properties, '$survey_response_abc123'),
        JSONExtractArrayRaw(properties, '$survey_response_1')
    )"""
        self.assertEqual(query, expected)
