export enum ProductTourEvent {
    CREATED = 'product tour created',
    UPDATED = 'product tour updated',
    LAUNCHED = 'product tour launched',
    STOPPED = 'product tour stopped',
    DELETED = 'product tour deleted',
    VIEWED = 'product tour viewed',
    LIST_VIEWED = 'product tour list viewed',
    STEP_ADDED = 'product tour step added',
    STEP_REMOVED = 'product tour step removed',
    PREVIEW_STARTED = 'product tour preview started',
    AI_GENERATED = 'product tour ai generated',
}

export type ProductTourCreationContext = 'app' | 'toolbar'
