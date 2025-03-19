#!/usr/bin/env python3
import sys
import json
import traceback

if __name__ == "__main__":
    try:
        for line in sys.stdin:
            value = json.loads(line)
            properties_json = value["properties"]
            question_index = int(value["question_index"])

            # Parse the properties JSON string
            properties = json.loads(properties_json)

            # Extract the survey name or return empty string if not found
            survey_name = properties.get("$survey_name", "")

            result = {"result": survey_name}
            print(json.dumps(result), end="\n")  # noqa: T201
            sys.stdout.flush()
    except Exception as e:
        # Log error to stderr
        print(f"Error: {str(e)}", file=sys.stderr)  # noqa: T201
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)  # Exit with non-zero code on error
