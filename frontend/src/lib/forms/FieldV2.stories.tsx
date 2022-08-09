import React from 'react'
import { ComponentMeta } from '@storybook/react'
import { FieldV2 } from './FieldV2'
import { LemonButton, LemonCheckbox, LemonDivider, LemonInput, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

export default {
    title: 'Forms/FieldV2',
    component: FieldV2,
    docs: {
        description: {
            component: `

[Related Figma area](https://www.figma.com/file/Y9G24U4r04nEjIDGIEGuKI/PostHog-Design-System-One?node-id=3139%3A1388)

Fields are a wrapping component that take care of rendering a label, input and error messages in a standard format.

They can be used in a kea-forms controlled way via \`Field\` or a pure way via \`PureField\`.
`,
        },
    },
} as ComponentMeta<typeof FieldV2>

// const Template: ComponentStory<typeof FieldV2> = (props: FieldV2Props) => {
//     return <FieldV2 {...props} />
// }

// export const Basic = Template.bind({})
// Basic.args = {
//     label: 'Check this out',
// }

export const Overview = (): JSX.Element => {
    return (
        <div className="space-y-4">
            <FieldV2
                label={
                    <>
                        Text input label <span>(Optional)</span>
                    </>
                }
                help={
                    <>
                        Optional descriptive or supportive text for the preceeding form element. This content can wrap
                        to multiple lines.
                    </>
                }
            >
                <LemonInput placeholder="Optional descriptive placeholder text" />
            </FieldV2>

            <FieldV2 label={'Select Label'} info={<>With info!</>}>
                <LemonSelect options={{ foo: { label: 'bar' } }} />
            </FieldV2>

            <FieldV2 label="Textarea Label" error="This field has an error">
                <LemonTextArea />
            </FieldV2>
            <FieldV2>
                <LemonCheckbox bordered label="Checkbox labels are set differently" />
            </FieldV2>

            <div className="flex justify-end gap-2 border-t mt-4 pt-4">
                <LemonButton type="secondary">Cancel</LemonButton>
                <LemonButton htmlType="submit" type="primary">
                    Submit
                </LemonButton>
            </div>
        </div>
    )
}
