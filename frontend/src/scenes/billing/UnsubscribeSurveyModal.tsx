import { LemonButton, LemonModal, LemonTextArea } from '@posthog/lemon-ui'
import { useMemo, useState } from 'react'
import { Survey } from 'posthog-js'

export const UnsubscribeSurveyModal = ({
    setSurvey,
    submitSurvey,
}: {
    setSurvey: (survey: Survey) => void
    submitSurvey: (textAreaValue: string) => void
}): JSX.Element | null => {
    const [textAreaValue, setTextAreaValue] = useState('')
    const textAreaNotEmpty = useMemo(() => textAreaValue.length > 0, [textAreaValue])
    return (
        <LemonModal
            onClose={() => {
                setSurvey(null)
            }}
            title="Let us know why you're unsubscribing"
        >
            <div className="flex flex-col">
                <LemonTextArea placeholder={'Start typing...'} value={textAreaValue} onChange={setTextAreaValue} />
                <div className="flex justify-end pt-2">
                    <LemonButton
                        type={textAreaNotEmpty ? 'primary' : 'tertiary'}
                        status={textAreaNotEmpty ? 'primary' : 'muted'}
                        onClick={() => {
                            submitSurvey(textAreaValue)
                            setSurvey(null)
                        }}
                    >
                        Unsubscribe
                    </LemonButton>
                </div>
            </div>
        </LemonModal>
    )
}
