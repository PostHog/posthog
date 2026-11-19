import './Today.scss'

import { useActions } from 'kea'

import { IconBug, IconCode, IconPalette, IconTrending } from '@posthog/icons'
import { Button } from '@posthog/quill'

import type { NewSessionSuggestionIcon } from 'products/tasks/frontend/spaces/newSessionSuggestionDefaults'

import { todayHomeComposerLogic } from './todayHomeComposerLogic'
import { TODAY_STARTER_SUGGESTIONS } from './todayStarterSuggestionList'

const ICONS: Partial<Record<NewSessionSuggestionIcon, JSX.Element>> = {
    code: <IconCode />,
    trends: <IconTrending />,
    bug: <IconBug />,
    canvas: <IconPalette />,
}

export function TodayStarterSuggestions(): JSX.Element {
    const { starterSuggestionSelected } = useActions(todayHomeComposerLogic)
    return (
        <div className="TodayStarterSuggestions" aria-label="Suggestions to get started" role="group">
            {TODAY_STARTER_SUGGESTIONS.map((suggestion, position) => (
                <Button
                    key={suggestion.id}
                    size="sm"
                    variant="outline"
                    title={suggestion.description}
                    onClick={() => starterSuggestionSelected(suggestion, position)}
                    data-attr="today-home-starter-suggestion"
                >
                    {ICONS[suggestion.icon]}
                    {suggestion.label}
                </Button>
            ))}
        </div>
    )
}
