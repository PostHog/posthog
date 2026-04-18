import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonColorPicker, LemonDivider, LemonInput, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { AuthorizedDomains } from './AuthorizedDomains'
import { supportSettingsLogic } from './supportSettingsLogic'

export function ConversationsWidgetConfigSetting(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const {
        isAddingDomain,
        editingDomainIndex,
        greetingInputValue,
        identificationFormTitleValue,
        identificationFormDescriptionValue,
        placeholderTextValue,
    } = useValues(supportSettingsLogic)
    const {
        setIsAddingDomain,
        setGreetingInputValue,
        saveGreetingText,
        setIdentificationFormTitleValue,
        saveIdentificationFormTitle,
        setIdentificationFormDescriptionValue,
        saveIdentificationFormDescription,
        setPlaceholderTextValue,
        savePlaceholderText,
    } = useActions(supportSettingsLogic)

    if (!currentTeam?.conversations_enabled) {
        return <p className="text-muted text-sm">Enable conversations API first.</p>
    }

    if (!currentTeam?.conversations_settings?.widget_enabled) {
        return <p className="text-muted text-sm">Enable the in-app widget first.</p>
    }

    return (
        <div className="space-y-4">
            <div>
                <div className="flex justify-between items-center gap-4">
                    <div>
                        <label className="font-medium">Allowed domains</label>
                        <p className="text-xs text-muted-alt">
                            Specify which domains can show the conversations widget. Leave empty to show on all domains.
                            Wildcards supported (e.g. https://*.example.com).
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

            <LemonDivider />

            <div className="flex items-center gap-4 justify-between">
                <label className="font-medium">Button color</label>
                <LemonColorPicker
                    colors={['#1d4aff', '#00aaff', '#00cc44', '#ffaa00', '#ff4444', '#9b59b6', '#1abc9c', '#000000']}
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

            <div className="flex items-center gap-4 justify-between">
                <label className="font-medium">Widget position</label>
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

            <div className="flex items-center gap-4 justify-between">
                <label className="font-medium">Greeting message</label>
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
                        disabledReason={!greetingInputValue ? 'Enter a greeting message' : undefined}
                    >
                        Save
                    </LemonButton>
                </div>
            </div>

            <LemonDivider />

            <div className="flex items-center gap-4 justify-between">
                <label className="font-medium">Placeholder text</label>
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
                        disabledReason={!placeholderTextValue ? 'Enter placeholder text' : undefined}
                    >
                        Save
                    </LemonButton>
                </div>
            </div>

            <LemonDivider />

            <h4 className="font-semibold mt-4">Identification form</h4>

            <div className="flex items-center gap-4 justify-between">
                <div>
                    <label className="font-medium">Require email</label>
                    <p className="text-xs text-muted-alt">
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
                    <div className="flex items-center gap-4 justify-between">
                        <div>
                            <label className="font-medium">Collect name</label>
                            <p className="text-xs text-muted-alt">Collect user's name to personalize the chat.</p>
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

                    <div className="flex items-center gap-4 justify-between">
                        <label className="font-medium">Form title</label>
                        <div className="flex gap-2 flex-1">
                            <LemonInput
                                value={
                                    identificationFormTitleValue ??
                                    currentTeam?.conversations_settings?.widget_identification_form_title ??
                                    'Before we start...'
                                }
                                placeholder="Enter form title"
                                onChange={setIdentificationFormTitleValue}
                                fullWidth
                            />
                            <LemonButton
                                type="primary"
                                onClick={saveIdentificationFormTitle}
                                disabledReason={!identificationFormTitleValue ? 'Enter form title' : undefined}
                            >
                                Save
                            </LemonButton>
                        </div>
                    </div>

                    <div className="flex items-center gap-4 justify-between">
                        <label className="font-medium">Form description</label>
                        <div className="flex gap-2 flex-1">
                            <LemonInput
                                value={
                                    identificationFormDescriptionValue ??
                                    currentTeam?.conversations_settings?.widget_identification_form_description ??
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
                                    !identificationFormDescriptionValue ? 'Enter form description' : undefined
                                }
                            >
                                Save
                            </LemonButton>
                        </div>
                    </div>
                </>
            )}
        </div>
    )
}
