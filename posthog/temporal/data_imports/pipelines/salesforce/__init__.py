"""Source for Salesforce depending on the simple_salesforce python package.

Imported resources are: account, campaign, contact, lead, opportunity, pricebook_2, pricebook_entry, product_2, user and user_role

Salesforce api docs: https://developer.salesforce.com/docs/apis

To get the security token: https://onlinehelp.coveo.com/en/ces/7.0/administrator/getting_the_security_token_for_your_salesforce_account.htm
"""

from dlt.sources import DltResource
from dlt.sources import incremental

from typing import Iterable

import dlt
from simple_salesforce import Salesforce
from dlt.common.typing import TDataItem


from .helpers import get_records


@dlt.source(name="salesforce", max_table_nesting=0)
def salesforce_source(
    subdomain: str,
    access_token: str,
    refresh_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    is_incremental: bool = False,
) -> Iterable[DltResource]:
    """
    Retrieves data from Salesforce using the Salesforce API.

    Args:
        user_name (str): The username for authentication. Defaults to the value in the `dlt.secrets` object.
        password (str): The password for authentication. Defaults to the value in the `dlt.secrets` object.
        security_token (str): The security token for authentication. Defaults to the value in the `dlt.secrets` object.

    Yields:
        DltResource: Data resources from Salesforce.
    """

    client = Salesforce(instance=f'{subdomain}.my.salesforce.com', session_id=access_token)


    # define resources
    @dlt.resource(write_disposition="replace")
    def sf_user() -> Iterable[TDataItem]:
        yield get_records(client, "User")

    @dlt.resource(write_disposition="replace")
    def user_role() -> Iterable[TDataItem]:
        yield get_records(client, "UserRole")

    @dlt.resource(write_disposition="merge")
    def opportunity(
        last_timestamp: incremental[str] = dlt.sources.incremental(
            "SystemModstamp", initial_value=None
        )
    ) -> Iterable[TDataItem]:
        yield get_records(
            client, "Opportunity", last_timestamp.last_value, "SystemModstamp"
        )

    @dlt.resource(write_disposition="merge")
    def opportunity_line_item(
        last_timestamp: incremental[str] = dlt.sources.incremental(
            "SystemModstamp", initial_value=None
        )
    ) -> Iterable[TDataItem]:
        yield get_records(
            client, "OpportunityLineItem", last_timestamp.last_value, "SystemModstamp"
        )

    @dlt.resource(write_disposition="merge")
    def opportunity_contact_role(
        last_timestamp: incremental[str] = dlt.sources.incremental(
            "SystemModstamp", initial_value=None
        )
    ) -> Iterable[TDataItem]:
        yield get_records(
            client,
            "OpportunityContactRole",
            last_timestamp.last_value,
            "SystemModstamp",
        )

    @dlt.resource(write_disposition="merge")
    def account(
        last_timestamp: incremental[str] = dlt.sources.incremental(
            "LastModifiedDate", initial_value=None
        )
    ) -> Iterable[TDataItem]:
        yield get_records(
            client, "Account", last_timestamp.last_value, "LastModifiedDate"
        )

    @dlt.resource(write_disposition="replace")
    def contact() -> Iterable[TDataItem]:
        yield get_records(client, "Contact")

    @dlt.resource(write_disposition="replace")
    def lead() -> Iterable[TDataItem]:
        yield get_records(client, "Lead")

    @dlt.resource(write_disposition="replace")
    def campaign() -> Iterable[TDataItem]:
        yield get_records(client, "Campaign")

    @dlt.resource(write_disposition="merge")
    def campaign_member(
        last_timestamp: incremental[str] = dlt.sources.incremental(
            "SystemModstamp", initial_value=None
        )
    ) -> Iterable[TDataItem]:
        yield get_records(
            client, "CampaignMember", last_timestamp.last_value, "SystemModstamp"
        )

    @dlt.resource(write_disposition="replace")
    def product_2() -> Iterable[TDataItem]:
        yield get_records(client, "Product2")

    @dlt.resource(write_disposition="replace")
    def pricebook_2() -> Iterable[TDataItem]:
        yield get_records(client, "Pricebook2")

    @dlt.resource(write_disposition="replace")
    def pricebook_entry() -> Iterable[TDataItem]:
        yield get_records(client, "PricebookEntry")

    @dlt.resource(write_disposition="merge")
    def task(
        last_timestamp: incremental[str] = dlt.sources.incremental(
            "SystemModstamp", initial_value=None
        )
    ) -> Iterable[TDataItem]:
        yield get_records(client, "Task", last_timestamp.last_value, "SystemModstamp")

    @dlt.resource(write_disposition="merge")
    def event(
        last_timestamp: incremental[str] = dlt.sources.incremental(
            "SystemModstamp", initial_value=None
        )
    ) -> Iterable[TDataItem]:
        yield get_records(client, "Event", last_timestamp.last_value, "SystemModstamp")

    return (
        sf_user,
        user_role,
        opportunity,
        opportunity_line_item,
        opportunity_contact_role,
        account,
        contact,
        lead,
        campaign,
        campaign_member,
        product_2,
        pricebook_2,
        pricebook_entry,
        task,
        event,
    )