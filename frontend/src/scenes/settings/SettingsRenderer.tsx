import { LemonButton } from '@posthog/lemon-ui'
import { IconLink } from 'lib/lemon-ui/icons'
import { SettingsLogicProps, settingsLogic } from './settingsLogic'
import { useActions, useValues } from 'kea'

export function SettingsRenderer(props: SettingsLogicProps): JSX.Element {
    const { settings } = useValues(settingsLogic(props))
    const { selectSetting } = useActions(settingsLogic(props))

    return (
        <div className="space-y-8">
            {settings.map((x) => (
                <div key={x.id} className="relative">
                    <div
                        id={x.id}
                        className="absolute" // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            marginTop: '-3.5rem', // Account for top bar when scrolling to anchor
                        }}
                    />
                    <h2 className="flex gap-2 items-center">
                        {x.title} <LemonButton icon={<IconLink />} size="small" onClick={() => selectSetting?.(x.id)} />
                    </h2>
                    {x.description && <p>{x.description}</p>}

                    {x.component}
                </div>
            ))}
        </div>
    )
}
