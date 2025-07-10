import { SurprisedHog } from 'lib/components/hedgehogs'

interface Props {
    type: 'question' | 'survey'
}

export function SurveyNoResponsesBanner({ type }: Props): JSX.Element {
    return (
        <div className="border-border flex w-full flex-col items-center justify-center gap-4 rounded border-2 border-dashed">
            <SurprisedHog className="size-36" />
            <div className="text-center">
                <h3 className="m-0 text-lg font-semibold">No responses for this {type}</h3>
                <p className="text-muted m-0 text-sm">
                    Once people start responding to your {type}, their answers will appear here.
                </p>
            </div>
        </div>
    )
}
