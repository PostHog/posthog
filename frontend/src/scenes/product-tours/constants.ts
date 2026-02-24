import { ProductTourAppearance } from '~/types'

export const DEFAULT_APPEARANCE: ProductTourAppearance = {
    backgroundColor: '#ffffff',
    textColor: '#1d1f27',
    buttonColor: '#1d1f27',
    borderRadius: 8,
    buttonBorderRadius: 6,
    borderColor: '#e5e7eb',
    fontFamily: 'system-ui',
    boxShadow: '0 4px 12px rgba(0, 0, 0, 0.15)',
    showOverlay: true,
    whiteLabel: false,
}

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
    CONSENT_SELECTED = 'product tour consent selected',
    RECORDING_STARTED = 'product tour recording started',
}

export type ProductTourCreationContext = 'app' | 'toolbar'
