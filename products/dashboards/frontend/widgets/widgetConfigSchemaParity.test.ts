// Guards FE Zod config keys against backend Pydantic JSON schema drift (cheap SSOT check).
import configPropertyKeys from '../generated/widget-config-property-keys.json'
import { errorTrackingWidgetConfigSchema, sessionReplayWidgetConfigSchema } from '../generated/widget-configs.zod'

const WIDGET_CONFIG_SCHEMAS = {
    error_tracking_list: errorTrackingWidgetConfigSchema,
    session_replay_list: sessionReplayWidgetConfigSchema,
} as const

describe('widget config schema parity', () => {
    it('frontend zod schemas expose the same top-level keys as backend pydantic', () => {
        for (const [widgetType, expectedKeys] of Object.entries(configPropertyKeys.configPropertyKeys)) {
            const schema = WIDGET_CONFIG_SCHEMAS[widgetType as keyof typeof WIDGET_CONFIG_SCHEMAS]
            expect(Object.keys(schema.shape).sort()).toEqual([...expectedKeys].sort())
        }
    })
})
