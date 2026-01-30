// Components
export { ProductSetupButton } from './ProductSetupButton'
export { ProductSetupPopover } from './ProductSetupPopover'

// Logic
export { productSetupLogic } from './productSetupLogic'
export type { ProductSetupLogicProps } from './productSetupLogic'

// Global setup logic for cross-product task completion and UI state
export { globalSetupLogic } from './globalSetupLogic'

// Registry
export {
    INGEST_FIRST_EVENT,
    SET_UP_REVERSE_PROXY,
    PRODUCT_SETUP_REGISTRY,
    PRODUCTS_WITH_SETUP,
    getProductSetupConfig,
    getTasksForProduct,
} from './productSetupRegistry'

// Hooks
export { useSetupHighlight } from './useSetupHighlight'

// Enums (must be exported as values, not types)
export { SetupTaskId } from './types'

// Types
export type { SetupTask, SetupTaskWithState, TaskType, ProductSetupConfig } from './types'
