"""Canonical, documentation-sourced descriptions for Salesforce standard objects and fields.

Sourced from the official Salesforce Object Reference for the Salesforce Platform
(https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/).
Keyed by the standard sObject API names in `settings.py` `ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Salesforce table. The source syncs a fixed set of standard
objects (it does not enumerate user-defined custom objects), so these are stable across teams.
Columns absent here fall back to LLM enrichment.
"""

from posthog.temporal.data_imports.sources.common.canonical_descriptions import CanonicalDescriptions

# Audit fields present on every standard Salesforce object; merged into each entry.
_COMMON_COLUMNS = {
    "Id": "Unique 18-character Salesforce record identifier.",
    "CreatedDate": "Date and time the record was created.",
    "CreatedById": "ID of the user who created the record.",
    "LastModifiedDate": "Date and time the record was last modified.",
    "LastModifiedById": "ID of the user who last modified the record.",
    "SystemModstamp": "Date and time the record was last modified by a user or automated process.",
    "IsDeleted": "Whether the record has been moved to the Recycle Bin.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Account": {
        "description": "An organization or person involved with your business, such as a customer or partner.",
        "docs_url": "https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/sforce_api_objects_account.htm",
        "columns": _columns(
            Name="Name of the account.",
            Type="Type of account (e.g. Customer, Partner, Prospect).",
            Industry="Primary business industry of the account.",
            Website="The account's website URL.",
            Phone="The account's primary phone number.",
            OwnerId="ID of the user who owns the account.",
            ParentId="ID of the parent account, if this account is part of a hierarchy.",
            AnnualRevenue="Estimated annual revenue of the account.",
            NumberOfEmployees="Number of employees at the account.",
            BillingCity="City portion of the account's billing address.",
            BillingCountry="Country portion of the account's billing address.",
            ShippingCity="City portion of the account's shipping address.",
            Description="Free-form text description of the account.",
        ),
    },
    "Contact": {
        "description": "An individual associated with an account, such as an employee of a customer.",
        "docs_url": "https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/sforce_api_objects_contact.htm",
        "columns": _columns(
            FirstName="Contact's first name.",
            LastName="Contact's last name.",
            Name="Contact's full name.",
            Email="Contact's email address.",
            Phone="Contact's phone number.",
            Title="Contact's job title.",
            AccountId="ID of the account this contact is associated with.",
            OwnerId="ID of the user who owns the contact.",
            ReportsToId="ID of the contact this person reports to.",
            MailingCity="City portion of the contact's mailing address.",
            MailingCountry="Country portion of the contact's mailing address.",
            LeadSource="Source from which this contact was generated.",
        ),
    },
    "Lead": {
        "description": "A prospect or potential customer who has not yet been qualified.",
        "docs_url": "https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/sforce_api_objects_lead.htm",
        "columns": _columns(
            FirstName="Lead's first name.",
            LastName="Lead's last name.",
            Name="Lead's full name.",
            Company="Company the lead is associated with.",
            Email="Lead's email address.",
            Phone="Lead's phone number.",
            Title="Lead's job title.",
            Status="Status of the lead in the qualification process.",
            LeadSource="Source from which this lead was generated.",
            Industry="Industry of the lead's company.",
            OwnerId="ID of the user who owns the lead.",
            IsConverted="Whether the lead has been converted into an account, contact, and opportunity.",
            ConvertedDate="Date the lead was converted.",
            ConvertedAccountId="ID of the account created when the lead was converted.",
            ConvertedContactId="ID of the contact created when the lead was converted.",
            ConvertedOpportunityId="ID of the opportunity created when the lead was converted.",
            Rating="Lead's rating (e.g. Hot, Warm, Cold).",
        ),
    },
    "Opportunity": {
        "description": "A potential sale or pending deal being tracked through the sales pipeline.",
        "docs_url": "https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/sforce_api_objects_opportunity.htm",
        "columns": _columns(
            Name="Name of the opportunity.",
            AccountId="ID of the account this opportunity is for.",
            Amount="Estimated total sale amount of the opportunity.",
            StageName="Current stage of the opportunity in the sales process.",
            Probability="Estimated percentage likelihood of closing the opportunity.",
            CloseDate="Expected or actual close date of the opportunity.",
            Type="Type of opportunity (e.g. New Business, Existing Business).",
            LeadSource="Source from which this opportunity was generated.",
            IsClosed="Whether the opportunity has reached a closed stage.",
            IsWon="Whether the opportunity was won.",
            ForecastCategoryName="Forecast category the opportunity falls into.",
            OwnerId="ID of the user who owns the opportunity.",
            ExpectedRevenue="Amount multiplied by probability — the weighted forecast revenue.",
        ),
    },
    "OpportunityHistory": {
        "description": "A historical snapshot of an opportunity's stage, amount, and probability at a point in time.",
        "docs_url": "https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/sforce_api_objects_opportunityhistory.htm",
        "columns": _columns(
            OpportunityId="ID of the opportunity this history record belongs to.",
            StageName="The opportunity's stage at the time of this snapshot.",
            Amount="The opportunity's amount at the time of this snapshot.",
            Probability="The opportunity's probability at the time of this snapshot.",
            CloseDate="The opportunity's close date at the time of this snapshot.",
            ForecastCategory="Forecast category at the time of this snapshot.",
        ),
    },
    "Campaign": {
        "description": "A marketing initiative, such as an email blast or event, used to generate leads.",
        "docs_url": "https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/sforce_api_objects_campaign.htm",
        "columns": _columns(
            Name="Name of the campaign.",
            Type="Type of campaign (e.g. Email, Webinar, Advertisement).",
            Status="Status of the campaign (e.g. Planned, In Progress, Completed).",
            StartDate="Start date of the campaign.",
            EndDate="End date of the campaign.",
            IsActive="Whether the campaign is currently active.",
            BudgetedCost="Budgeted cost of the campaign.",
            ActualCost="Actual cost incurred by the campaign.",
            ExpectedRevenue="Expected revenue generated by the campaign.",
            NumberOfLeads="Number of leads associated with the campaign.",
            NumberOfContacts="Number of contacts associated with the campaign.",
            OwnerId="ID of the user who owns the campaign.",
        ),
    },
    "User": {
        "description": "A user account in the Salesforce organization.",
        "docs_url": "https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/sforce_api_objects_user.htm",
        "columns": _columns(
            Username="The user's login username, in email format.",
            Name="The user's full name.",
            FirstName="The user's first name.",
            LastName="The user's last name.",
            Email="The user's email address.",
            IsActive="Whether the user account is active.",
            ProfileId="ID of the user's profile, which controls permissions.",
            UserRoleId="ID of the user's role in the role hierarchy.",
            Title="The user's job title.",
            Department="The user's department.",
            ManagerId="ID of the user's manager.",
            TimeZoneSidKey="The user's time zone.",
        ),
    },
    "UserRole": {
        "description": "A role in the organization's role hierarchy, controlling record-level data access.",
        "docs_url": "https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/sforce_api_objects_userrole.htm",
        "columns": _columns(
            Name="Name of the role.",
            ParentRoleId="ID of the parent role in the hierarchy.",
            DeveloperName="Unique API name of the role.",
            RollupDescription="Description of the role used in forecasting rollups.",
        ),
    },
    "Product2": {
        "description": "A product or service your organization sells, used in price books and opportunities.",
        "docs_url": "https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/sforce_api_objects_product2.htm",
        "columns": _columns(
            Name="Name of the product.",
            ProductCode="Internal product code or SKU.",
            Description="Description of the product.",
            IsActive="Whether the product is active and available for use.",
            Family="Product family the product belongs to.",
            QuantityUnitOfMeasure="Unit of measure for the product (e.g. each, kg).",
        ),
    },
    "Pricebook2": {
        "description": "A price book — a list of products and their prices for a given market or segment.",
        "docs_url": "https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/sforce_api_objects_pricebook2.htm",
        "columns": _columns(
            Name="Name of the price book.",
            Description="Description of the price book.",
            IsActive="Whether the price book is active.",
            IsStandard="Whether this is the standard (default) price book.",
        ),
    },
    "PricebookEntry": {
        "description": "An entry linking a product to a price within a specific price book.",
        "docs_url": "https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/sforce_api_objects_pricebookentry.htm",
        "columns": _columns(
            Name="Name of the price book entry (typically the product name).",
            Pricebook2Id="ID of the price book this entry belongs to.",
            Product2Id="ID of the product this entry prices.",
            UnitPrice="Price of the product in this price book.",
            IsActive="Whether the price book entry is active.",
            UseStandardPrice="Whether this entry uses the standard price.",
            CurrencyIsoCode="ISO currency code for the unit price.",
        ),
    },
    "Order": {
        "description": "An agreement between a company and an account to provision products or services.",
        "docs_url": "https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/sforce_api_objects_order.htm",
        "columns": _columns(
            OrderNumber="Auto-generated reference number for the order.",
            AccountId="ID of the account the order is for.",
            Status="Status of the order (e.g. Draft, Activated).",
            EffectiveDate="Date the order takes effect.",
            EndDate="Date the order ends.",
            TotalAmount="Total amount of all order products.",
            Type="Type of order.",
            OwnerId="ID of the user who owns the order.",
            Pricebook2Id="ID of the price book associated with the order.",
            OpportunityId="ID of the opportunity the order originated from, if any.",
        ),
    },
    "Event": {
        "description": "A calendar event, such as a meeting or call, logged against a record.",
        "docs_url": "https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/sforce_api_objects_event.htm",
        "columns": _columns(
            Subject="Subject line of the event.",
            StartDateTime="Date and time the event starts.",
            EndDateTime="Date and time the event ends.",
            ActivityDate="Due date of the event.",
            Location="Location of the event.",
            OwnerId="ID of the user who owns the event.",
            WhoId="ID of the contact or lead associated with the event.",
            WhatId="ID of the related record (e.g. account or opportunity) for the event.",
            IsAllDayEvent="Whether the event lasts all day.",
            Description="Description or notes for the event.",
        ),
    },
    "Task": {
        "description": "A to-do item, such as a call or follow-up, logged against a record.",
        "docs_url": "https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/sforce_api_objects_task.htm",
        "columns": _columns(
            Subject="Subject line of the task.",
            Status="Status of the task (e.g. Not Started, In Progress, Completed).",
            Priority="Priority of the task (e.g. High, Normal, Low).",
            ActivityDate="Due date of the task.",
            OwnerId="ID of the user the task is assigned to.",
            WhoId="ID of the contact or lead associated with the task.",
            WhatId="ID of the related record (e.g. account or opportunity) for the task.",
            IsClosed="Whether the task is in a closed state.",
            Description="Description or notes for the task.",
        ),
    },
}
