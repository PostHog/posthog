import { ActivityDescriber as errorTrackingActivityDescriber } from '@posthog/products-error-tracking/frontend/components/ActivityDescriber'

import { instanceSettingActivityDescriber } from 'lib/components/ActivityLog/activityDescriptions/instanceSettingActivityDescriber'
import { tagActivityDescriber } from 'lib/components/ActivityLog/activityDescriptions/tagActivityDescriber'
import { ActivityLogItem, Describer, defaultDescriber } from 'lib/components/ActivityLog/humanizeActivity'
import { actionActivityDescriber } from 'scenes/actions/actionActivityDescriber'
import { alertConfigurationActivityDescriber } from 'scenes/alerts/activityDescriptions'
import { annotationActivityDescriber } from 'scenes/annotations/activityDescriptions'
import { userActivityDescriber } from 'scenes/authentication/shared/activityDescriptions'
import { cohortActivityDescriber } from 'scenes/cohorts/activityDescriptions'
import { dashboardActivityDescriber } from 'scenes/dashboard/dashboardActivityDescriber'
import { dataManagementActivityDescriber } from 'scenes/data-management/dataManagementDescribers'
import { batchExportActivityDescriber } from 'scenes/data-pipelines/batch-exports/activityDescriptions'
import { batchImportActivityDescriber } from 'scenes/data-pipelines/batch-imports/activityDescriptions'
import { dataWarehouseSavedQueryActivityDescriber } from 'scenes/data-warehouse/saved_queries/activityDescriptions'
import { experimentActivityDescriber } from 'scenes/experiments/experimentActivityDescriber'
import { exportedAssetActivityDescriber } from 'scenes/exports/activityDescriptions'
import { flagActivityDescriber } from 'scenes/feature-flags/activityDescriptions'
import { groupActivityDescriber } from 'scenes/groups/activityDescriptions'
import { hogFunctionActivityDescriber } from 'scenes/hog-functions/misc/activityDescriptions'
import { notebookActivityDescriber } from 'scenes/notebooks/Notebook/notebookActivityDescriber'
import { personActivityDescriber } from 'scenes/persons/activityDescriptions'
import { productTourActivityDescriber } from 'scenes/product-tours/activityDescriptions'
import { insightActivityDescriber } from 'scenes/saved-insights/activityDescriptions'
import { replayActivityDescriber } from 'scenes/session-recordings/activityDescription'
import {
    legalDocumentActivityDescriber,
    organizationActivityDescriber,
    organizationDomainActivityDescriber,
} from 'scenes/settings/organization/activityDescriptions'
import { projectSecretAPIKeyActivityDescriber } from 'scenes/settings/project/activityDescriptions'
import {
    oauthApplicationActivityDescriber,
    personalAPIKeyActivityDescriber,
} from 'scenes/settings/user/activityDescriptions'
import { surveyActivityDescriber } from 'scenes/surveys/surveyActivityDescriber'
import { teamActivityDescriber } from 'scenes/team-activity/teamActivityDescriber'

import { ActivityScope } from '~/types'

import { ticketActivityDescriber } from 'products/conversations/frontend/activityDescriber'
import { externalDataSourceActivityDescriber } from 'products/data_warehouse/frontend/shared/components/activityDescriptions'
import { endpointActivityDescriber } from 'products/endpoints/frontend/activityDescriber'
import { signalScoutConfigActivityDescriber } from 'products/signals/frontend/activityDescriber'
import { workflowActivityDescriber } from 'products/workflows/frontend/Workflows/misc/workflowActivityDescriber'

export const describerFor = (logItem?: ActivityLogItem): Describer | undefined => {
    switch (logItem?.scope) {
        case ActivityScope.ACTION:
            return actionActivityDescriber
        case ActivityScope.ALERT_CONFIGURATION:
            return alertConfigurationActivityDescriber
        case ActivityScope.ANNOTATION:
            return annotationActivityDescriber
        case ActivityScope.BATCH_EXPORT:
            return batchExportActivityDescriber
        case ActivityScope.BATCH_IMPORT:
            return batchImportActivityDescriber
        case ActivityScope.EXPORTED_ASSET:
            return exportedAssetActivityDescriber
        case ActivityScope.DASHBOARD:
            return dashboardActivityDescriber
        case ActivityScope.FEATURE_FLAG:
            return flagActivityDescriber
        case ActivityScope.HOG_FUNCTION:
            return hogFunctionActivityDescriber
        case ActivityScope.HOG_FLOW:
            return workflowActivityDescriber
        case ActivityScope.COHORT:
            return cohortActivityDescriber
        case ActivityScope.INSIGHT:
            return insightActivityDescriber
        case ActivityScope.INSTANCE_SETTING:
            return instanceSettingActivityDescriber
        case ActivityScope.PERSON:
            return personActivityDescriber
        case ActivityScope.PERSONAL_API_KEY:
            return personalAPIKeyActivityDescriber
        case ActivityScope.PROJECT_SECRET_API_KEY:
            return projectSecretAPIKeyActivityDescriber
        case ActivityScope.GROUP:
            return groupActivityDescriber
        case ActivityScope.EVENT_DEFINITION:
        case ActivityScope.PROPERTY_DEFINITION:
            return dataManagementActivityDescriber
        case ActivityScope.NOTEBOOK:
            return notebookActivityDescriber
        case ActivityScope.TEAM:
            return teamActivityDescriber
        case ActivityScope.ORGANIZATION:
        case ActivityScope.ORGANIZATION_MEMBERSHIP:
        case ActivityScope.ORGANIZATION_INVITE:
            return organizationActivityDescriber
        case ActivityScope.ORGANIZATION_DOMAIN:
            return organizationDomainActivityDescriber
        case ActivityScope.OAUTH_APPLICATION:
            return oauthApplicationActivityDescriber
        case ActivityScope.LEGAL_DOCUMENT:
            return legalDocumentActivityDescriber
        case ActivityScope.SURVEY:
            return surveyActivityDescriber
        case ActivityScope.ERROR_TRACKING_ISSUE:
            return errorTrackingActivityDescriber
        case ActivityScope.DATA_WAREHOUSE_SAVED_QUERY:
            return dataWarehouseSavedQueryActivityDescriber
        case ActivityScope.REPLAY:
            return replayActivityDescriber
        case ActivityScope.HEATMAP:
            return defaultDescriber
        case ActivityScope.EXPERIMENT:
            return experimentActivityDescriber
        case ActivityScope.TAG:
        case ActivityScope.TAGGED_ITEM:
            return tagActivityDescriber
        case ActivityScope.EXTERNAL_DATA_SOURCE:
        case ActivityScope.EXTERNAL_DATA_SCHEMA:
            return externalDataSourceActivityDescriber
        case ActivityScope.USER:
            return userActivityDescriber
        case ActivityScope.ENDPOINT:
        case ActivityScope.ENDPOINT_VERSION:
            return endpointActivityDescriber
        case ActivityScope.PRODUCT_TOUR:
            return productTourActivityDescriber
        case ActivityScope.TICKET:
            return ticketActivityDescriber
        case ActivityScope.SIGNAL_SCOUT_CONFIG:
            return signalScoutConfigActivityDescriber
        default:
            return defaultDescriber
    }
}
