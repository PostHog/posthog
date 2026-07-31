import { LemonSwitch } from '@posthog/lemon-ui'

import { SourceConfig, SourceFieldSelectConfig, SourceFieldSwitchGroupConfig } from '~/queries/schema/schema-general'

import { sourceFieldToElement } from './SourceForm'

const SELECT_FIELD: SourceFieldSelectConfig = {
    type: 'select',
    name: 'response_types',
    label: 'Responses to sync',
    required: false,
    defaultValue: 'completed',
    options: [
        { label: 'Completed responses only', value: 'completed' },
        { label: 'All responses (including partial & started)', value: 'completed,partial,started' },
    ],
    caption: 'Changing this triggers a full refresh of the responses table.',
}

const SWITCH_GROUP_FIELD: SourceFieldSwitchGroupConfig = {
    type: 'switch-group',
    name: 'custom_properties',
    label: 'Customize synced properties',
    default: false,
    fields: [],
}

const SOURCE_CONFIG = { name: 'Typeform', fields: [] } as unknown as SourceConfig

describe('sourceFieldToElement', () => {
    it('renders a select field caption as field help text', () => {
        const element = sourceFieldToElement(SELECT_FIELD, SOURCE_CONFIG)
        expect(element.props.help).toBeTruthy()
    })

    it('omits help when a select field has no caption', () => {
        const element = sourceFieldToElement({ ...SELECT_FIELD, caption: undefined }, SOURCE_CONFIG)
        expect(element.props.help).toBeUndefined()
    })

    it.each([
        ['False', false],
        ['True', true],
        [true, true],
        [false, false],
        [undefined, false],
    ])('renders the switch as %p when the stored enabled value is %p', (storedEnabled, expectedChecked) => {
        // job_inputs round-trips booleans as Python-style strings ('True'/'False'). 'False' is
        // JS-truthy, so a naive `!!value` check would render a saved-disabled switch as checked.
        const lastValue = { custom_properties: { enabled: storedEnabled } }
        const element = sourceFieldToElement(SWITCH_GROUP_FIELD, SOURCE_CONFIG, lastValue)
        const rendered = (element.props.children as (props: any) => any)({ value: undefined, onChange: jest.fn() })
        const switchElement = rendered.props.children.find((child: any) => child?.type === LemonSwitch)
        expect(switchElement.props.checked).toBe(expectedChecked)
    })
})
