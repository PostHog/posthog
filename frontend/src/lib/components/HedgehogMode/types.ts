import type {
    HedgehogActor as _HedgehogActor,
    HedgehogActorOptions as _HedgehogActorOptions,
    HedgehogModeConfig as _HedgehogModeConfig,
    HedgehogModeInterface as _HedgehogModeInterface,
} from '@posthog/hedgehog-mode'

// NOTE: For whatever reason, kea-typegen can't navigate the exported class, so we need to do this
export interface HedgehogModeInterface extends _HedgehogModeInterface {}
export interface HedgehogActor extends _HedgehogActor {}
export interface HedgehogModeConfig extends _HedgehogModeConfig {}
export interface HedgehogActorOptions extends _HedgehogActorOptions {}
