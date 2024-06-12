from typing import Optional, TypedDict

from dlt.common import pendulum
from dlt.common.time import ensure_pendulum_datetime
from dlt.common.typing import DictStrAny, DictStrStr, TDataItem


class TCustomFieldInfo(TypedDict):
    title: str
    options: DictStrStr


def _parse_date_or_none(value: Optional[str]) -> Optional[pendulum.DateTime]:
    if not value:
        return None
    return ensure_pendulum_datetime(value)


def process_ticket(
    ticket: DictStrAny,
    custom_fields: dict[str, TCustomFieldInfo],
    pivot_custom_fields: bool = True,
) -> DictStrAny:
    """
    Helper function that processes a ticket object and returns a dictionary of ticket data.

    Args:
        ticket: The ticket dict object returned by a Zendesk API call.
        custom_fields: A dictionary containing all the custom fields available for tickets.
        pivot_custom_fields: A boolean indicating whether to pivot all custom fields or not.
            Defaults to True.

    Returns:
        DictStrAny: A dictionary containing cleaned data about a ticket.
    """
    # Commented out due to how slow this processing code is, and how often it'd break the pipeline.
    # to be revisited on whether we want/need this pre-processing and figure out the best way to do it.

    # pivot custom field if indicated as such
    # get custom fields
    # pivoted_fields = set()
    # for custom_field in ticket.get("custom_fields", []):
    #     if pivot_custom_fields:
    #         cus_field_id = str(custom_field["id"])
    #         field = custom_fields.get(cus_field_id, None)
    #         if field is None:
    #             logger.warning(
    #                 "Custom field with ID %s does not exist in fields state. It may have been created after the pipeline run started.",
    #                 cus_field_id,
    #             )
    #             custom_field["ticket_id"] = ticket["id"]
    #             continue

    #         pivoted_fields.add(cus_field_id)
    #         field_name = field["title"]
    #         current_value = custom_field["value"]
    #         options = field["options"]
    #         # Map dropdown values to labels
    #         if not current_value or not options:
    #             ticket[field_name] = current_value
    #         elif isinstance(current_value, list):  # Multiple choice field has a list of values
    #             ticket[field_name] = [options.get(key, key) for key in current_value]
    #         else:
    #             ticket[field_name] = options.get(current_value)
    #     else:
    #         custom_field["ticket_id"] = ticket["id"]
    # # delete fields that are not needed for pivoting
    # if pivot_custom_fields:
    #     ticket["custom_fields"] = [f for f in ticket.get("custom_fields", []) if str(f["id"]) not in pivoted_fields]
    #     if not ticket.get("custom_fields"):
    #         del ticket["custom_fields"]
    # del ticket["fields"]

    # modify dates to return datetime objects instead
    ticket["updated_at"] = _parse_date_or_none(ticket["updated_at"])
    ticket["created_at"] = _parse_date_or_none(ticket["created_at"])
    ticket["due_at"] = _parse_date_or_none(ticket["due_at"])
    return ticket


def process_ticket_field(field: DictStrAny, custom_fields_state: dict[str, TCustomFieldInfo]) -> TDataItem:
    """Update custom field mapping in dlt state for the given field."""
    # grab id and update state dict
    # if the id is new, add a new key to indicate that this is the initial value for title
    # New dropdown options are added to existing field but existing options are not changed
    return_dict = field.copy()
    field_id = str(field["id"])

    options = field.get("custom_field_options", [])
    new_options = {o["value"]: o["name"] for o in options}
    existing_field = custom_fields_state.get(field_id)
    if existing_field:
        existing_options = existing_field["options"]
        if return_options := return_dict.get("custom_field_options"):
            for item in return_options:
                item["name"] = existing_options.get(item["value"], item["name"])
        for key, value in new_options.items():
            if key not in existing_options:
                existing_options[key] = value
    else:
        custom_fields_state[field_id] = {"title": field["title"], "options": new_options}
        return_dict["initial_title"] = field["title"]
    return return_dict
