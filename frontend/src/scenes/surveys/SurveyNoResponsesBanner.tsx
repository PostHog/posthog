import { SurprisedHog } from 'lib/components/hedgehogs'

interface Props {
    type: 'question' | 'survey'
}

export function SurveyNoResponsesBanner({ type }: Props): JSX.Element {
    return (
        <div className="border-2 border-dashed border-border w-full rounded flex flex-col items-center justify-center gap-4">
            <SurprisedHog className="size-36" />
            <div className="text-center">
                <h3 className="text-lg font-semibold m-0">No responses for this {type}</h3>
                <p className="text-sm text-muted m-0">
                    Once people start responding to your {type}, their answers will appear here.
                </p>
            </div>
        </div>
    )
}
