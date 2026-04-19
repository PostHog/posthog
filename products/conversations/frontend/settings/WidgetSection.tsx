import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCard,
    LemonColorPicker,
    LemonDivider,
    LemonInput,
    LemonSelect,
    LemonSwitch,
    Link,
} from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { AuthorizedDomains } from './AuthorizedDomains'
import { supportSettingsLogic } from './supportSettingsLogic'

export function WidgetSection(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const {
        generateNewToken,
        setIsAddingDomain,
        setWidgetEnabledLoading,
        setGreetingInputValue,
        saveGreetingText,
        setIdentificationFormTitleValue,
        saveIdentificationFormTitle,
        setIdentificationFormDescriptionValue,
        saveIdentificationFormDescription,
        setPlaceholderTextValue,
        savePlaceholderText,
    } = useActions(supportSettingsLogic)
    const {
        isAddingDomain,
        editingDomainIndex,
        widgetEnabledLoading,
        greetingInputValue,
        identificationFormTitleValue,
        identificationFormDescriptionValue,
        placeholderTextValue,
    } = useValues(supportSettingsLogic)

    return (
        <SceneSection
            title="In-app widget"
            description={
                <>
                    Add a chat widget to your website for customers to reach you.{' '}
                    <Link to="https://posthog.com/docs/support/widget" target="_blank">
                        Docs
                    </Link>
                </>
            }
        >
            <LemonCard hoverEffect={false} className="flex flex-col gap-y-2 max-w-[800px] px-4 py-3">
                <div className="flex items-center gap-4 justify-between">
                    <div>
                        <label className="w-40 shrink-0 font-medium">Enable in-app widget</label>
                        <p className="text-xs text-muted-alt">
                            Turn on the in-app support widget to start receiving messages from your users
                        </p>
                    </div>
                    <LemonSwitch
                        checked={!!currentTeam?.conversations_settings?.widget_enabled}
                        onChange={(checked) => {
                            setWidgetEnabledLoading(true)
                            updateCurrentTeam({
                                conversations_settings: {
                                    ...currentTeam?.conversations_settings,
                                    widget_enabled: checked,
                                },
                            })
                        }}
                        loading={widgetEnabledLoading}
                    />
                </div>

                {currentTeam?.conversations_settings?.widget_enabled && (
                    <>
                        <LemonDivider />
                        <div>
                            <div className="flex justify-between items-center gap-4">
                                <div>
                                    <label className="w-40 shrink-0 font-medium">Allowed domains</label>
                                    <p className="text-xs text-muted-alt">
                                        Specify which domains can show the conversations widget. Leave empty to show on
                                        all domains. Wildcards supported (e.g. https://*.example.com).
                                    </p>
                                </div>
                                {!isAddingDomain && editingDomainIndex === null && (
                                    <LemonButton
                                        onClick={() => setIsAddingDomain(true)}
                                        type="secondary"
                                        icon={<IconPlus />}
                                        size="small"
                                    >
                                        Add domain
                                    </LemonButton>
                                )}
                            </div>
                            <AuthorizedDomains />
                        </div>
                        <SceneSection title="Visual settings" className="mt-8" titleSize="sm">
                            <LemonCard hoverEffect={false} className="px-4 py-3">
                                <div className="flex items-center gap-4 py-2 justify-between">
                                    <label className="w-40 shrink-0 font-medium">Button color</label>
                                    <LemonColorPicker
                                        colors={[
                                            '#1d4aff',
                                            '#00aaff',
                                            '#00cc44',
                                            '#ffaa00',
                                            '#ff4444',
                                            '#9b59b6',
                                            '#1abc9c',
                                            '#000000',
                                        ]}
                                        selectedColor={currentTeam?.conversations_settings?.widget_color || '#1d4aff'}
                                        onSelectColor={(color) => {
                                            updateCurrentTeam({
                                                conversations_settings: {
                                                    ...currentTeam?.conversations_settings,
                                                    widget_color: color,
                                                },
                                            })
                                        }}
                                        showCustomColor
                                    />
                                </div>
                                <LemonDivider />
                                <div className="flex items-center gap-4 py-2 justify-between">
                                    <label className="w-40 shrink-0 font-medium">Widget position</label>
                                    <LemonSelect
                                        value={currentTeam?.conversations_settings?.widget_position || 'bottom_right'}
                                        onChange={(value) => {
                                            updateCurrentTeam({
                                                conversations_settings: {
                                                    ...currentTeam?.conversations_settings,
                                                    widget_position: value,
                                                },
                                            })
                                        }}
                                        options={[
                                            { value: 'bottom_right', label: 'Bottom right' },
                                            { value: 'bottom_left', label: 'Bottom left' },
                                            { value: 'top_right', label: 'Top right' },
                                            { value: 'top_left', label: 'Top left' },
                                        ]}
                                    />
                                </div>
                                <LemonDivider />
                                <div className="flex items-center gap-4 py-2 justify-between">
                                    <label className="w-40 shrink-0 font-medium">Greeting message</label>
                                    <div className="flex gap-2 flex-1">
                                        <LemonInput
                                            value={
                                                greetingInputValue ??
                                                currentTeam?.conversations_settings?.widget_greeting_text ??
                                                'Hey, how can I help you today?'
                                            }
                                            placeholder="Enter greeting message"
                                            onChange={setGreetingInputValue}
                                            fullWidth
                                        />
                                        <LemonButton
                                            type="primary"
                                            onClick={saveGreetingText}
                                            disabledReason={
                                                !greetingInputValue ? 'Enter a greeting message' : undefined
                                            }
                                        >
                                            Save
                                        </LemonButton>
                                    </div>
                                </div>
                                <LemonDivider />
                                <div className="flex items-center gap-4 py-2 justify-between">
                                    <label className="w-40 shrink-0 font-medium">Placeholder text</label>
                                    <div className="flex gap-2 flex-1">
                                        <LemonInput
                                            value={
                                                placeholderTextValue ??
                                                currentTeam?.conversations_settings?.widget_placeholder_text ??
                                                'Type your message...'
                                            }
                                            placeholder="Enter placeholder text"
                                            onChange={setPlaceholderTextValue}
                                            fullWidth
                                        />
                                        <LemonButton
                                            type="primary"
                                            onClick={savePlaceholderText}
                                            disabledReason={
                                                !placeholderTextValue ? 'Enter placeholder text' : undefined
                                            }
                                        >
                                            Save
                                        </LemonButton>
                                    </div>
                                </div>
                            </LemonCard>
                        </SceneSection>
                        <SceneSection title="Identification form" className="mt-8" titleSize="sm">
                            <LemonCard hoverEffect={false} className="px-4 py-3">
                                <div className="flex items-center gap-4 py-2 justify-between">
                                    <div>
                                        <label className="w-40 shrink-0 font-medium">Require email</label>
                                        <p className="text-xs text-muted-alt mb-2">
                                            Require user to enter their email address to start the chat.
                                        </p>
                                    </div>
                                    <LemonSwitch
                                        checked={!!currentTeam?.conversations_settings?.widget_require_email}
                                        onChange={(checked) => {
                                            updateCurrentTeam({
                                                conversations_settings: {
                                                    ...currentTeam?.conversations_settings,
                                                    widget_require_email: checked,
                                                },
                                            })
                                        }}
                                    />
                                </div>

                                {currentTeam?.conversations_settings?.widget_require_email && (
                                    <>
                                        <LemonDivider />
                                        <div className="flex items-center gap-4 py-2 justify-between">
                                            <div>
                                                <label className="w-40 shrink-0 font-medium">Collect name</label>
                                                <p className="text-xs text-muted-alt mb-2">
                                                    Collect user's name to personalize the chat.
                                                </p>
                                            </div>
                                            <LemonSwitch
                                                checked={!!currentTeam?.conversations_settings?.widget_collect_name}
                                                onChange={(checked) => {
                                                    updateCurrentTeam({
                                                        conversations_settings: {
                                                            ...currentTeam?.conversations_settings,
                                                            widget_collect_name: checked,
                                                        },
                                                    })
                                                }}
                                            />
                                        </div>
                                        <LemonDivider />
                                        <div className="flex items-center gap-4 py-2 justify-between">
                                            <label className="w-40 shrink-0 font-medium">Form title</label>
                                            <div className="flex gap-2 flex-1">
                                                <LemonInput
                                                    value={
                                                        identificationFormTitleValue ??
                                                        currentTeam?.conversations_settings
                                                            ?.widget_identification_form_title ??
                                                        'Before we start...'
                                                    }
                                                    placeholder="Enter form title"
                                                    onChange={setIdentificationFormTitleValue}
                                                    fullWidth
                                                />
                                                <LemonButton
                                                    type="primary"
                                                    onClick={saveIdentificationFormTitle}
                                                    disabledReason={
                                                        !identificationFormTitleValue ? 'Enter form title' : undefined
                                                    }
                                                >
                                                    Save
                                                </LemonButton>
                                            </div>
                                        </div>
                                        <LemonDivider />
                                        <div className="flex items-center gap-4 py-2 justify-between">
                                            <label className="w-40 shrink-0 font-medium">Form description</label>
                                            <div className="flex gap-2 flex-1">
                                                <LemonInput
                                                    value={
                                                        identificationFormDescriptionValue ??
                                                        currentTeam?.conversations_settings
                                                            ?.widget_identification_form_description ??
                                                        'Please provide your details so we can help you better.'
                                                    }
                                                    placeholder="Enter form description"
                                                    onChange={setIdentificationFormDescriptionValue}
                                                    fullWidth
                                                />
                                                <LemonButton
                                                    type="primary"
                                                    onClick={saveIdentificationFormDescription}
                                                    disabledReason={
                                                        !identificationFormDescriptionValue
                                                            ? 'Enter form description'
                                                            : undefined
                                                    }
                                                >
                                                    Save
                                                </LemonButton>
                                            </div>
                                        </div>
                                    </>
                                )}
                            </LemonCard>
                        </SceneSection>
                        <div className="pt-8">
                            <div className="flex items-center gap-4 py-2 justify-between">
                                <div>
                                    <label className="w-40 shrink-0 font-medium">Public token</label>
                                    <p className="text-xs text-muted-alt mb-2">
                                        Automatically generated token used to authenticate widget requests.
                                    </p>
                                </div>
                                <div className="flex gap-2 flex-1">
                                    <LemonInput
                                        value={
                                            currentTeam?.conversations_settings?.widget_public_token ||
                                            'Token will be auto-generated on save'
                                        }
                                        disabledReason="Read-only after generation"
                                        fullWidth
                                    />
                                    {currentTeam?.conversations_settings?.widget_public_token && (
                                        <LemonButton type="secondary" status="danger" onClick={generateNewToken}>
                                            Regenerate
                                        </LemonButton>
                                    )}
                                </div>
                            </div>
                            <LemonBanner type="warning" className="my-2">
                                Only regenerate if you suspect it has been exposed or compromised.
                            </LemonBanner>
                        </div>
                    </>
                )}
            </LemonCard>
        </SceneSection>
    )
}
