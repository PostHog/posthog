import { LemonButton, LemonTabs } from "@posthog/lemon-ui";

enum ResultsTab {
    Results = 'results',
    Visualization = 'visualization'
}

export function ResultPane(): JSX.Element {
    return (
        <div className="flex w-full flex-1 bg-bg-3000">
            <div className="flex flex-row justify-between align-center py-2 px-4 w-full h-[55px]">
                <LemonTabs
                    activeKey={ResultsTab.Results}
                    onChange={() => {

                    }}
                    tabs={[
                        {
                            key: ResultsTab.Results,
                            label: "Results"
                        },
                        {
                            key: ResultsTab.Visualization,
                            label: "Visualization"
                        }
                    ]}
                />
                <div className="flex gap-1">
                    <LemonButton type="secondary">
                        Save
                    </LemonButton>
                    <LemonButton type="primary">
                        Run
                    </LemonButton>
                </div>
            </div>
            <div className="flex-1">

            </div>
        </div>
    )
}
