import { useValues } from 'kea'
import { Field, Form } from 'kea-forms'

import { textCardConverter } from 'lib/components/Cards/TextCard/textCardMarkdown'
import { TextCardModalBodyField } from 'lib/components/Cards/TextCard/TextCardModalBodyField'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { DashboardTextEditorProps, dashboardTextEditorLogic } from './dashboardTextEditorLogic'

export function DashboardTextEditor({
    onCancel,
    ...props
}: DashboardTextEditorProps & { onCancel: () => void }): JSX.Element {
    const { isTextSubmitting, saveFailed } = useValues(dashboardTextEditorLogic(props))
    return (
        <Form logic={dashboardTextEditorLogic} props={props} formKey="text" enableFormOnSubmit className="p-4">
            <Field name="body" label="Dashboard text">
                {({ value, onChange }) => (
                    <TextCardModalBodyField
                        shouldUseLegacyMarkdownEditor={!textCardConverter.isRoundTripSafe(props.initialBody)}
                        value={value}
                        onChange={onChange}
                    />
                )}
            </Field>
            {saveFailed && <p role="alert">Could not save this text. Try again.</p>}
            <div className="mt-2 flex justify-end gap-2">
                <LemonButton
                    type="secondary"
                    onClick={onCancel}
                    disabledReason={isTextSubmitting ? 'Saving text' : null}
                >
                    Cancel
                </LemonButton>
                <LemonButton type="primary" htmlType="submit" loading={isTextSubmitting}>
                    Save
                </LemonButton>
            </div>
        </Form>
    )
}
