/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import {
    AccountApi,
    AccountNotebookApi,
    AccountRelationshipDefinitionApi,
    AccountRelationshipWriteApi,
    AnnouncementApi,
    CustomPropertyDefinitionApi,
    CustomPropertySourceApi,
    CustomPropertySourceUpdateApi,
    CustomPropertyValueWriteApi,
    CustomerJourneyApi,
    CustomerProfileConfigApi,
    EventStreamApi,
    EventStreamMemberWriteApi,
    GroupUsageMetricApi,
    PatchedAccountApi,
    PatchedAccountRelationshipDefinitionApi,
    PatchedCustomPropertyDefinitionApi,
    PatchedCustomPropertySourceUpdateApi,
    PatchedCustomerJourneyApi,
    PatchedCustomerProfileConfigApi,
    PatchedEventStreamApi,
    PatchedGroupUsageMetricApi,
} from './api.zod.schemas'

export const AccountRelationshipDefinitionsCreateBody = AccountRelationshipDefinitionApi

export const AccountRelationshipDefinitionsUpdateBody = AccountRelationshipDefinitionApi

export const AccountRelationshipDefinitionsPartialUpdateBody = PatchedAccountRelationshipDefinitionApi

export const AccountsCreateBody = AccountApi

export const AccountsCustomPropertyValuesCreateBody = CustomPropertyValueWriteApi

export const AccountsNotebooksCreateBody = AccountNotebookApi

export const AccountsRelationshipsCreateBody = AccountRelationshipWriteApi

export const AccountsUpdateBody = AccountApi

export const AccountsPartialUpdateBody = PatchedAccountApi

export const AnnouncementsCreateBody = AnnouncementApi

export const CustomPropertyDefinitionsCreateBody = CustomPropertyDefinitionApi

export const CustomPropertyDefinitionsUpdateBody = CustomPropertyDefinitionApi

export const CustomPropertyDefinitionsPartialUpdateBody = PatchedCustomPropertyDefinitionApi

export const CustomPropertySourcesCreateBody = CustomPropertySourceApi

export const CustomPropertySourcesUpdateBody = CustomPropertySourceUpdateApi

export const CustomPropertySourcesPartialUpdateBody = PatchedCustomPropertySourceUpdateApi

export const CustomerJourneysCreateBody = CustomerJourneyApi

export const CustomerJourneysUpdateBody = CustomerJourneyApi

export const CustomerJourneysPartialUpdateBody = PatchedCustomerJourneyApi

export const CustomerProfileConfigsCreateBody = CustomerProfileConfigApi

export const CustomerProfileConfigsUpdateBody = CustomerProfileConfigApi

export const CustomerProfileConfigsPartialUpdateBody = PatchedCustomerProfileConfigApi

/**
 * The caller's event stream: a live feed of selected accounts' events posted to a
 * Slack channel of their choice. Per-user — each team member owns at most one stream, and
 * every endpoint is scoped to the caller's own. Delivery runs through a managed CDP
 * destination that is re-provisioned inside the same transaction as every write, so
 * config and delivery can't drift apart.
 */
export const EventStreamsCreateBody = EventStreamApi

/**
 * The caller's event stream: a live feed of selected accounts' events posted to a
 * Slack channel of their choice. Per-user — each team member owns at most one stream, and
 * every endpoint is scoped to the caller's own. Delivery runs through a managed CDP
 * destination that is re-provisioned inside the same transaction as every write, so
 * config and delivery can't drift apart.
 */
export const EventStreamsUpdateBody = EventStreamApi

/**
 * The caller's event stream: a live feed of selected accounts' events posted to a
 * Slack channel of their choice. Per-user — each team member owns at most one stream, and
 * every endpoint is scoped to the caller's own. Delivery runs through a managed CDP
 * destination that is re-provisioned inside the same transaction as every write, so
 * config and delivery can't drift apart.
 */
export const EventStreamsPartialUpdateBody = PatchedEventStreamApi

/**
 * The caller's event stream: a live feed of selected accounts' events posted to a
 * Slack channel of their choice. Per-user — each team member owns at most one stream, and
 * every endpoint is scoped to the caller's own. Delivery runs through a managed CDP
 * destination that is re-provisioned inside the same transaction as every write, so
 * config and delivery can't drift apart.
 */
export const EventStreamsAddAccountCreateBody = EventStreamMemberWriteApi

/**
 * The caller's event stream: a live feed of selected accounts' events posted to a
 * Slack channel of their choice. Per-user — each team member owns at most one stream, and
 * every endpoint is scoped to the caller's own. Delivery runs through a managed CDP
 * destination that is re-provisioned inside the same transaction as every write, so
 * config and delivery can't drift apart.
 */
export const EventStreamsRemoveAccountCreateBody = EventStreamMemberWriteApi

export const GroupsTypesMetricsCreateBody = GroupUsageMetricApi

export const GroupsTypesMetricsUpdateBody = GroupUsageMetricApi

export const GroupsTypesMetricsPartialUpdateBody = PatchedGroupUsageMetricApi
