import re
import csv
import sys
import json
import uuid
from collections.abc import Generator

import structlog

from posthog.schema import LLMTrace, LLMTracePerson

logger = structlog.get_logger(__name__)
csv.field_size_limit(sys.maxsize)


def load_traces_from_csv_files(csv_paths: list[str]) -> Generator[LLMTrace, None, None]:
    """Load traces from CSV files, useful for local development."""
    # The assumption is that the CSV was exported through default Traces query runner query
    fields_to_column_mapping = {
        "id": 0,
        "createdAt": 1,
        "person": 2,
        "totalLatency": 3,
        "inputTokens": 4,
        "outputTokens": 5,
        "inputCost": 6,
        "outputCost": 7,
        "totalCost": 8,
        "inputState": 9,
        "outputState": 10,
        "traceName": 11,
    }
    for csv_path in csv_paths:
        with open(csv_path) as file:
            reader = csv.reader(file)
            # Skip header
            next(reader)
            for row in reader:
                output_state_raw = row[fields_to_column_mapping["outputState"]]
                if not output_state_raw:
                    continue
                output_state = json.loads(output_state_raw)
                input_state_raw = row[fields_to_column_mapping["inputState"]]
                if not input_state_raw:
                    input_state = {}  # Allowing empty, as it's not used in calculations
                else:
                    input_state = json.loads(input_state_raw)
                # Create a person with minimal data (uuid and email)
                raw_person_data = row[fields_to_column_mapping["person"]]
                person_uuids_search = re.findall(r"UUID\('(.*?)'\)", raw_person_data)
                if not person_uuids_search:
                    logger.warning(f"No person UUID found for person: {raw_person_data.splitlines()[0]}")
                    continue
                person_uuid = person_uuids_search[0]
                properties = {}
                person_emails_search = re.findall(r'"email":"(.*?)"', raw_person_data)
                if person_emails_search:
                    person_email = person_emails_search[0]
                    properties["email"] = person_email
                person = LLMTracePerson(
                    created_at=row[fields_to_column_mapping["createdAt"]],
                    distinct_id=str(uuid.uuid4()),  # Not used in calculations
                    properties=properties,
                    uuid=person_uuid,
                )
                # Process other properties, could be skipped, for now, as not used for calculations
                input_cost = row[fields_to_column_mapping["inputCost"]] or 0
                input_tokens = row[fields_to_column_mapping["inputTokens"]] or 0
                output_cost = row[fields_to_column_mapping["outputCost"]] or 0
                output_tokens = row[fields_to_column_mapping["outputTokens"]] or 0
                total_cost = row[fields_to_column_mapping["totalCost"]] or 0
                total_latency = row[fields_to_column_mapping["totalLatency"]]
                trace_name = row[fields_to_column_mapping["traceName"]]
                # Create LLM trace object
                trace = LLMTrace(
                    aiSessionId=str(uuid.uuid4()),  # Not used in calculations
                    createdAt=row[fields_to_column_mapping["createdAt"]],
                    errorCount=0,  # Not used in calculations
                    events=[],  # Not used in calculations
                    id=row[fields_to_column_mapping["id"]],
                    inputCost=input_cost,
                    inputState=input_state,
                    inputTokens=input_tokens,
                    outputCost=output_cost,
                    outputState=output_state,
                    outputTokens=output_tokens,
                    person=person,
                    totalCost=total_cost,
                    totalLatency=total_latency,
                    traceName=trace_name,
                )
                yield trace
