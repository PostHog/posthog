import { useActions, useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { LemonButton, LemonDivider, LemonInput, LemonSwitch, Link } from '@posthog/lemon-ui'
import { useState } from 'react'

export enum SettingValueType {
    Boolean = 'boolean',
    Text = 'text',
    Number = 'number',
}

export interface ExtraSettingType {
    name: string
    description: string
    key: string
    moreInfo: string
    valueType: SettingValueType
}

const AVAILABLE_EXTRA_SETTINGS: ExtraSettingType[] = [
    {
        name: 'Person on Events (Beta)',
        description: `We have updated our data model to also store person properties directly on events, making queries significantly faster. This means that person properties will no longer be "timeless", but rather point-in-time i.e. on filters we'll consider a person's properties at the time of the event, rather than at present time. This may cause data to change on some of your insights, but will be the default way we handle person properties going forward. For now, you can control whether you want this on or not, and should feel free to let us know of any concerns you might have. If you do enable this, you should see speed improvements of around 3-5x on average on most of your insights.`,
        moreInfo:
            'https://github.com/PostHog/posthog/blob/75a2111f2c4f9183dd45f85c7b103c7b0524eabf/plugin-server/src/worker/ingestion/PoE.md',
        key: 'poe_v2_enabled',
        valueType: SettingValueType.Boolean,
    },
]

function ExtraSettingInput({
    defaultValue,
    type,
    settingKey,
}: {
    defaultValue?: string | number
    type: 'number' | 'text'
    settingKey: string
}): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    const [value, setValue] = useState(defaultValue)

    return (
        <div className="space-y-4 max-w-160">
            <LemonInput value={value as any} onChange={setValue} disabled={currentTeamLoading} type={type as any} />
            <LemonButton
                type="primary"
                onClick={() =>
                    updateCurrentTeam({ extra_settings: { ...currentTeam?.extra_settings, [settingKey]: value } })
                }
                loading={currentTeamLoading}
            >
                Update
            </LemonButton>
        </div>
    )
}

export function ExtraTeamSettings(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    return (
        <>
            {AVAILABLE_EXTRA_SETTINGS.map((setting) => (
                <>
                    <h2 className="subtitle" id={`extra_settings_${setting.key}`}>
                        {setting.name}
                    </h2>
                    <div className="space-y-2">
                        <p>
                            {setting.description}
                            {setting.moreInfo ? <Link to={setting.moreInfo}> More info.</Link> : null}
                        </p>
                        {setting.valueType === SettingValueType.Boolean ? (
                            <LemonSwitch
                                data-attr={`extra_settings_${setting.key}`}
                                onChange={(checked) => {
                                    updateCurrentTeam({
                                        extra_settings: { ...currentTeam?.extra_settings, [setting.key]: checked },
                                    })
                                }}
                                label={`Enable ${setting.name}`}
                                checked={!!currentTeam?.extra_settings?.[setting.key]}
                                bordered
                            />
                        ) : (
                            <ExtraSettingInput
                                defaultValue={currentTeam?.extra_settings?.[setting.key] as string | number | undefined}
                                type={setting.valueType}
                                settingKey={setting.key}
                            />
                        )}
                    </div>
                    <LemonDivider className="my-6" />
                </>
            ))}
        </>
    )
}
