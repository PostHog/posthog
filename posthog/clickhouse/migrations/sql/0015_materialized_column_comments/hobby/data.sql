ALTER TABLE events ON CLUSTER 'posthog' COMMENT COLUMN IF EXISTS properties_issampledevent 'column_materializer::isSampledEvent'

ALTER TABLE events ON CLUSTER 'posthog' COMMENT COLUMN IF EXISTS properties_currentscreen 'column_materializer::currentScreen'

ALTER TABLE events ON CLUSTER 'posthog' COMMENT COLUMN IF EXISTS properties_objectname 'column_materializer::objectName'
