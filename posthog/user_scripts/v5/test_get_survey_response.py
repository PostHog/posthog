#!/usr/bin/env python3
import unittest
import json
import io
from unittest.mock import patch
import os
import importlib.util

# Import the script as a module
script_path = os.path.join(os.path.dirname(__file__), "get_survey_response.py")
spec = importlib.util.spec_from_file_location("get_survey_response", script_path)
if spec is not None:
    get_survey_response = importlib.util.module_from_spec(spec)
    if spec.loader is not None:
        spec.loader.exec_module(get_survey_response)
else:
    raise ImportError(f"Could not import get_survey_response.py from {script_path}")


class TestGetSurveyResponse(unittest.TestCase):
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_old_format_array_of_strings(self, mock_stdout):
        # Test case 1: survey_questions is an array of strings (old format)
        test_input = {
            "properties": json.dumps(
                {"$survey_questions": ["Question 1", "Question 2", "Question 3"], "$survey_response": "Answer to Q1"}
            ),
            "question_index": 0,
            "question_id": "",
        }

        with patch("sys.stdin", io.StringIO(json.dumps(test_input) + "\n")):
            get_survey_response.main() if hasattr(get_survey_response, "main") else get_survey_response.__dict__[
                "__name__"
            ]

        output = json.loads(mock_stdout.getvalue().strip())
        self.assertEqual(output["result"], "Answer to Q1")

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_old_format_with_question_index(self, mock_stdout):
        # Test case 2: old format with question_index > 0
        test_input = {
            "properties": json.dumps(
                {"$survey_questions": ["Question 1", "Question 2", "Question 3"], "$survey_response_1": "Answer to Q2"}
            ),
            "question_index": 1,
            "question_id": "",
        }

        with patch("sys.stdin", io.StringIO(json.dumps(test_input) + "\n")):
            get_survey_response.main() if hasattr(get_survey_response, "main") else get_survey_response.__dict__[
                "__name__"
            ]

        output = json.loads(mock_stdout.getvalue().strip())
        self.assertEqual(output["result"], "Answer to Q2")

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_new_format_array_of_dicts(self, mock_stdout):
        # Test case 3: survey_questions is an array of dictionaries (new format)
        test_input = {
            "properties": json.dumps(
                {
                    "$survey_questions": [
                        {"id": "q1", "index": 0, "name": "Question 1"},
                        {"id": "q2", "index": 1, "name": "Question 2"},
                    ],
                    "$survey_response_q1": "Answer to Q1",
                }
            ),
            "question_index": 0,
            "question_id": "",
        }

        with patch("sys.stdin", io.StringIO(json.dumps(test_input) + "\n")):
            get_survey_response.main() if hasattr(get_survey_response, "main") else get_survey_response.__dict__[
                "__name__"
            ]

        output = json.loads(mock_stdout.getvalue().strip())
        self.assertEqual(output["result"], "Answer to Q1")

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_direct_question_id(self, mock_stdout):
        # Test case 4: question_id is passed directly
        test_input = {
            "properties": json.dumps(
                {
                    "$survey_questions": [
                        {"id": "q1", "index": 0, "name": "Question 1"},
                        {"id": "q2", "index": 1, "name": "Question 2"},
                    ],
                    "$survey_response_custom_id": "Answer to custom ID question",
                }
            ),
            "question_index": 0,
            "question_id": "custom_id",
        }

        with patch("sys.stdin", io.StringIO(json.dumps(test_input) + "\n")):
            get_survey_response.main() if hasattr(get_survey_response, "main") else get_survey_response.__dict__[
                "__name__"
            ]

        output = json.loads(mock_stdout.getvalue().strip())
        self.assertEqual(output["result"], "Answer to custom ID question")

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_missing_response(self, mock_stdout):
        # Test case 5: Response is missing
        test_input = {
            "properties": json.dumps({"$survey_questions": ["Question 1", "Question 2", "Question 3"]}),
            "question_index": 0,
            "question_id": "",
        }

        with patch("sys.stdin", io.StringIO(json.dumps(test_input) + "\n")):
            get_survey_response.main() if hasattr(get_survey_response, "main") else get_survey_response.__dict__[
                "__name__"
            ]

        output = json.loads(mock_stdout.getvalue().strip())
        self.assertEqual(output["result"], "")

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_no_survey_questions(self, mock_stdout):
        # Test case 6: No survey_questions array
        test_input = {
            "properties": json.dumps({"$survey_response": "Answer to Q1"}),
            "question_index": 0,
            "question_id": "",
        }

        with patch("sys.stdin", io.StringIO(json.dumps(test_input) + "\n")):
            get_survey_response.main() if hasattr(get_survey_response, "main") else get_survey_response.__dict__[
                "__name__"
            ]

        output = json.loads(mock_stdout.getvalue().strip())
        self.assertEqual(output["result"], "Answer to Q1")

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_mixed_format_preference(self, mock_stdout):
        # Test case 7: Both id and index-based responses exist, id should be preferred
        test_input = {
            "properties": json.dumps(
                {
                    "$survey_questions": [{"id": "q1", "index": 0, "name": "Question 1"}],
                    "$survey_response": "Index-based answer",
                    "$survey_response_q1": "ID-based answer",
                }
            ),
            "question_index": 0,
            "question_id": "q1",
        }

        with patch("sys.stdin", io.StringIO(json.dumps(test_input) + "\n")):
            get_survey_response.main() if hasattr(get_survey_response, "main") else get_survey_response.__dict__[
                "__name__"
            ]

        output = json.loads(mock_stdout.getvalue().strip())
        self.assertEqual(output["result"], "ID-based answer")

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_question_index_out_of_bounds(self, mock_stdout):
        # Test case 8: question_index is out of bounds
        test_input = {
            "properties": json.dumps(
                {
                    "$survey_questions": ["Question 1", "Question 2"],
                    "$survey_response_5": "Answer to out of bounds question",
                }
            ),
            "question_index": 5,  # Out of bounds index
            "question_id": "",
        }

        with patch("sys.stdin", io.StringIO(json.dumps(test_input) + "\n")):
            get_survey_response.main() if hasattr(get_survey_response, "main") else get_survey_response.__dict__[
                "__name__"
            ]

        output = json.loads(mock_stdout.getvalue().strip())
        self.assertEqual(output["result"], "Answer to out of bounds question")


if __name__ == "__main__":
    unittest.main()
