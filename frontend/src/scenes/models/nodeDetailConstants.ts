export { NODE_TYPE_TAG_SETTINGS, STATUS_TAG_SETTINGS } from 'products/data_modeling/frontend/lineage/nodeStyles'

// Mirrors the backend `Node.description` limit (products/data_modeling/backend/models/node.py).
// Keep in sync if the model's max_length changes.
export const NODE_DESCRIPTION_MAX_LENGTH = 1024
