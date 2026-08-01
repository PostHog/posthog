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

const SOURCE_CONFIG = { name: 'Typeform', fields: [] } as unknown as SourceConfig

const SWITCH_GROUP_FIELD: SourceFieldSwitchGroupConfig = {
    type: 'switch-group',
    name: 'custom_properties',
    label: 'Customize synced properties',
    default: false,
    fields: [
        {
            type: 'textarea',
            name: 'deals_properties',
            label: 'Deals properties',
            required: false,
            placeholder: '',
            secret: false,
        },
    ],
}

// Renders the switch group and reports the toggle's checked state alongside whether its child
// fields expanded — the bug was precisely those two disagreeing.
const switchGroupState = (storedGroupValue: any, formValue?: any): { checked: boolean; childrenVisible: boolean } => {
    const element = sourceFieldToElement(SWITCH_GROUP_FIELD, SOURCE_CONFIG, storedGroupValue)
    const rendered = element.props.children({ value: formValue, onChange: jest.fn() })
    const children = Array.isArray(rendered.props.children) ? rendered.props.children : [rendered.props.children]
    const toggle = children.find((child: any) => child && child.props && 'checked' in child.props)
    if (!toggle) {
        throw new Error('switch group rendered no toggle')
    }
    return { checked: toggle.props.checked, childrenVisible: !!children.find((child: any) => child?.props?.name) }
}

describe('sourceFieldToElement', () => {
    it('renders a select field caption as field help text', () => {
        const element = sourceFieldToElement(SELECT_FIELD, SOURCE_CONFIG)
        expect(element.props.help).toBeTruthy()
    })

    it('omits help when a select field has no caption', () => {
        const element = sourceFieldToElement({ ...SELECT_FIELD, caption: undefined }, SOURCE_CONFIG)
        expect(element.props.help).toBeUndefined()
    })

    // job_inputs cross an encrypted field that stringifies booleans, so the form prefills `enabled`
    // as "True"/"False". LemonSwitch checks `checked === true`, so an untranslated "True" rendered
    // the toggle off while the truthy string still expanded the children below it.
    it.each([
        ['prefilled as the string True', undefined, 'True', true],
        ['prefilled as the string False', undefined, 'False', false],
        ['toggled on in the form', undefined, true, true],
        ['stored as the string True before the prefill lands', { enabled: 'True' }, undefined, true],
        ['never configured', undefined, undefined, false],
        ['toggled off in the form over a stored True', { enabled: 'True' }, false, false],
    ])('reflects a switch group %s', (_name, storedGroupValue, formValue, expected) => {
        expect(switchGroupState(storedGroupValue, formValue)).toEqual({
            checked: expected,
            childrenVisible: expected,
        })
    })
})
