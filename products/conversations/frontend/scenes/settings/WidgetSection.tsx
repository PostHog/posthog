import { useActions, useValues } from 'kea'
import type { ChangeEvent } from 'react'

import { Link } from 'lib/lemon-ui/Link'
import {
    Button,
    Card,
    CardContent,
    Input,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Separator,
    Spinner,
    Switch,
} from 'lib/ui/quill'
import { teamLogic } from 'scenes/teamLogic'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { supportSettingsLogic } from './supportSettingsLogic'

const WIDGET_COLORS = ['#1d4aff', '#00aaff', '#00cc44', '#ffaa00', '#ff4444', '#9b59b6', '#1abc9c', '#000000']

function WidgetColorPicker({
    selectedColor,
    onSelectColor,
}: {
    selectedColor: string
    onSelectColor: (color: string) => void
}): JSX.Element {
    return (
        <div className="flex flex-wrap items-center gap-1">
            {WIDGET_COLORS.map((color) => (
                <Button
                    key={color}
                    type="button"
                    variant="outline"
                    size="icon-sm"
                    aria-label={color}
                    aria-pressed={selectedColor === color}
                    title={color}
                    onClick={() => onSelectColor(color)}
                >
                    <span className="size-4 rounded-full border" style={{ backgroundColor: color }} />
                </Button>
            ))}
            <Input
                type="color"
                aria-label="Custom color"
                value={selectedColor}
                onChange={(e: ChangeEvent<HTMLInputElement>) => onSelectColor(e.target.value)}
                className="size-8 cursor-pointer p-0"
            />
        </div>
    )
}

export function WidgetSection(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const {
        generateNewToken,
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
        widgetEnabledLoading,
        greetingInputValue,
        identificationFormTitleValue,
        identificationFormDescriptionValue,
        placeholderTextValue,
    } = useValues(supportSettingsLogic)

    const greetingDisabledReason = !greetingInputValue ? 'Enter a greeting message' : undefined
    const placeholderDisabledReason = !placeholderTextValue ? 'Enter placeholder text' : undefined
    const formTitleDisabledReason = !identificationFormTitleValue ? 'Enter form title' : undefined
    const formDescriptionDisabledReason = !identificationFormDescriptionValue ? 'Enter form description' : undefined

    return (
        <SceneSection
            title="In-app widget"
            description={
                <>
                    Add a chat widget to your website for customers to reach you.{' '}
                    <Link to="https://posthog.com/docs/support/widget" target="_blank">
                        Docs
                    </Link>
                    . For logged-in users, use{' '}
                    <Link
                        to="https://posthog.com/docs/support/javascript-api#user-identification"
                        target="_blank"
                        targetBlankIcon
                    >
                        identity verification
                    </Link>{' '}
                    so tickets persist across browsers and devices.
                </>
            }
        >
            <Card size="sm" className="max-w-[800px]">
                <CardContent className="flex flex-col gap-y-2">
                    <div className="flex items-center gap-4 justify-between">
                        <div>
                            <label className="w-40 shrink-0 font-medium">Enable in-app widget</label>
                            <p className="text-xs text-muted-alt">
                                Turn on the in-app support widget to start receiving messages from your users
                            </p>
                        </div>
                        <div className="flex items-center gap-2">
                            {widgetEnabledLoading ? <Spinner /> : null}
                            <Switch
                                checked={!!currentTeam?.conversations_settings?.widget_enabled}
                                disabled={widgetEnabledLoading}
                                onCheckedChange={(checked) => {
                                    setWidgetEnabledLoading(true)
                                    updateCurrentTeam({
                                        conversations_settings: {
                                            ...currentTeam?.conversations_settings,
                                            widget_enabled: checked,
                                        },
                                    })
                                }}
                            />
                        </div>
                    </div>

                    {currentTeam?.conversations_settings?.widget_enabled && (
                        <>
                            <Separator />
                            <div className="rounded border border-primary bg-surface-secondary p-2 text-sm my-2">
                                Allowed domains for the widget are managed under the <strong>Direct API</strong> section
                                — they apply to both the widget and direct API calls.
                            </div>
                            <SceneSection title="Visual settings" className="mt-8" titleSize="sm">
                                <Card size="sm">
                                    <CardContent>
                                        <div className="flex items-center gap-4 py-2 justify-between">
                                            <label className="w-40 shrink-0 font-medium">Button color</label>
                                            <WidgetColorPicker
                                                selectedColor={
                                                    currentTeam?.conversations_settings?.widget_color || '#1d4aff'
                                                }
                                                onSelectColor={(color) => {
                                                    updateCurrentTeam({
                                                        conversations_settings: {
                                                            ...currentTeam?.conversations_settings,
                                                            widget_color: color,
                                                        },
                                                    })
                                                }}
                                            />
                                        </div>
                                        <Separator />
                                        <div className="flex items-center gap-4 py-2 justify-between">
                                            <label className="w-40 shrink-0 font-medium">Widget position</label>
                                            <Select
                                                value={
                                                    currentTeam?.conversations_settings?.widget_position ||
                                                    'bottom_right'
                                                }
                                                onValueChange={(value) => {
                                                    if (
                                                        value !== 'bottom_right' &&
                                                        value !== 'bottom_left' &&
                                                        value !== 'top_right' &&
                                                        value !== 'top_left'
                                                    ) {
                                                        return
                                                    }
                                                    updateCurrentTeam({
                                                        conversations_settings: {
                                                            ...currentTeam?.conversations_settings,
                                                            widget_position: value,
                                                        },
                                                    })
                                                }}
                                            >
                                                <SelectTrigger size="sm">
                                                    <SelectValue placeholder="Select position" />
                                                </SelectTrigger>
                                                <SelectContent>
                                                    <SelectItem value="bottom_right">Bottom right</SelectItem>
                                                    <SelectItem value="bottom_left">Bottom left</SelectItem>
                                                    <SelectItem value="top_right">Top right</SelectItem>
                                                    <SelectItem value="top_left">Top left</SelectItem>
                                                </SelectContent>
                                            </Select>
                                        </div>
                                        <Separator />
                                        <div className="flex items-center gap-4 py-2 justify-between">
                                            <label className="w-40 shrink-0 font-medium">Greeting message</label>
                                            <div className="flex gap-2 flex-1">
                                                <Input
                                                    className="w-full"
                                                    value={
                                                        greetingInputValue ??
                                                        currentTeam?.conversations_settings?.widget_greeting_text ??
                                                        'Hey, how can I help you today?'
                                                    }
                                                    placeholder="Enter greeting message"
                                                    onChange={(e: ChangeEvent<HTMLInputElement>) =>
                                                        setGreetingInputValue(e.target.value)
                                                    }
                                                />
                                                <Button
                                                    variant="primary"
                                                    onClick={saveGreetingText}
                                                    disabled={!!greetingDisabledReason}
                                                    title={greetingDisabledReason}
                                                >
                                                    Save
                                                </Button>
                                            </div>
                                        </div>
                                        <Separator />
                                        <div className="flex items-center gap-4 py-2 justify-between">
                                            <label className="w-40 shrink-0 font-medium">Placeholder text</label>
                                            <div className="flex gap-2 flex-1">
                                                <Input
                                                    className="w-full"
                                                    value={
                                                        placeholderTextValue ??
                                                        currentTeam?.conversations_settings?.widget_placeholder_text ??
                                                        'Type your message...'
                                                    }
                                                    placeholder="Enter placeholder text"
                                                    onChange={(e: ChangeEvent<HTMLInputElement>) =>
                                                        setPlaceholderTextValue(e.target.value)
                                                    }
                                                />
                                                <Button
                                                    variant="primary"
                                                    onClick={savePlaceholderText}
                                                    disabled={!!placeholderDisabledReason}
                                                    title={placeholderDisabledReason}
                                                >
                                                    Save
                                                </Button>
                                            </div>
                                        </div>
                                    </CardContent>
                                </Card>
                            </SceneSection>
                            <SceneSection title="Identification form" className="mt-8" titleSize="sm">
                                <Card size="sm">
                                    <CardContent>
                                        <div className="flex items-center gap-4 py-2 justify-between">
                                            <div>
                                                <label className="w-40 shrink-0 font-medium">Require email</label>
                                                <p className="text-xs text-muted-alt mb-2">
                                                    Require user to enter their email address to start the chat.
                                                </p>
                                            </div>
                                            <Switch
                                                checked={!!currentTeam?.conversations_settings?.widget_require_email}
                                                onCheckedChange={(checked) => {
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
                                                <Separator />
                                                <div className="flex items-center gap-4 py-2 justify-between">
                                                    <div>
                                                        <label className="w-40 shrink-0 font-medium">
                                                            Collect name
                                                        </label>
                                                        <p className="text-xs text-muted-alt mb-2">
                                                            Collect user's name to personalize the chat.
                                                        </p>
                                                    </div>
                                                    <Switch
                                                        checked={
                                                            !!currentTeam?.conversations_settings?.widget_collect_name
                                                        }
                                                        onCheckedChange={(checked) => {
                                                            updateCurrentTeam({
                                                                conversations_settings: {
                                                                    ...currentTeam?.conversations_settings,
                                                                    widget_collect_name: checked,
                                                                },
                                                            })
                                                        }}
                                                    />
                                                </div>
                                                <Separator />
                                                <div className="flex items-center gap-4 py-2 justify-between">
                                                    <label className="w-40 shrink-0 font-medium">Form title</label>
                                                    <div className="flex gap-2 flex-1">
                                                        <Input
                                                            className="w-full"
                                                            value={
                                                                identificationFormTitleValue ??
                                                                currentTeam?.conversations_settings
                                                                    ?.widget_identification_form_title ??
                                                                'Before we start...'
                                                            }
                                                            placeholder="Enter form title"
                                                            onChange={(e: ChangeEvent<HTMLInputElement>) =>
                                                                setIdentificationFormTitleValue(e.target.value)
                                                            }
                                                        />
                                                        <Button
                                                            variant="primary"
                                                            onClick={saveIdentificationFormTitle}
                                                            disabled={!!formTitleDisabledReason}
                                                            title={formTitleDisabledReason}
                                                        >
                                                            Save
                                                        </Button>
                                                    </div>
                                                </div>
                                                <Separator />
                                                <div className="flex items-center gap-4 py-2 justify-between">
                                                    <label className="w-40 shrink-0 font-medium">
                                                        Form description
                                                    </label>
                                                    <div className="flex gap-2 flex-1">
                                                        <Input
                                                            className="w-full"
                                                            value={
                                                                identificationFormDescriptionValue ??
                                                                currentTeam?.conversations_settings
                                                                    ?.widget_identification_form_description ??
                                                                'Please provide your details so we can help you better.'
                                                            }
                                                            placeholder="Enter form description"
                                                            onChange={(e: ChangeEvent<HTMLInputElement>) =>
                                                                setIdentificationFormDescriptionValue(e.target.value)
                                                            }
                                                        />
                                                        <Button
                                                            variant="primary"
                                                            onClick={saveIdentificationFormDescription}
                                                            disabled={!!formDescriptionDisabledReason}
                                                            title={formDescriptionDisabledReason}
                                                        >
                                                            Save
                                                        </Button>
                                                    </div>
                                                </div>
                                            </>
                                        )}
                                    </CardContent>
                                </Card>
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
                                        <Input
                                            className="w-full"
                                            value={
                                                currentTeam?.conversations_settings?.widget_public_token ||
                                                'Token will be auto-generated on save'
                                            }
                                            disabled
                                            title="Read-only after generation"
                                        />
                                        {currentTeam?.conversations_settings?.widget_public_token && (
                                            <Button variant="destructive" onClick={generateNewToken}>
                                                Regenerate
                                            </Button>
                                        )}
                                    </div>
                                </div>
                                <div className="rounded border border-warning bg-warning-highlight p-2 text-sm my-2">
                                    Only regenerate if you suspect it has been exposed or compromised.
                                </div>
                            </div>
                        </>
                    )}
                </CardContent>
            </Card>
        </SceneSection>
    )
}
