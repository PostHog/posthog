import { LemonBanner } from '@posthog/lemon-ui'

import { EditableField } from 'lib/components/EditableField/EditableField'

import { SurveyAppearance } from '~/types'

import { isIntroScreenShown } from '../../surveyIntroScreen'
import { ScreenEditorCard } from './ScreenEditorCard'

interface IntroScreenEditorProps {
    appearance: SurveyAppearance
    onUpdate: (updates: Partial<SurveyAppearance>) => void
    onToggle: (enabled: boolean) => void
}

export function IntroScreenEditor({ appearance, onUpdate, onToggle }: IntroScreenEditorProps): JSX.Element {
    return (
        <ScreenEditorCard title="Intro screen" enabled={appearance.displayIntroScreen ?? false} onToggle={onToggle}>
            {!isIntroScreenShown(appearance) && (
                <LemonBanner type="warning">
                    The intro screen won't show until it has a header or a description.
                </LemonBanner>
            )}
            <EditableField
                name="intro-header"
                value={appearance.introScreenHeader || ''}
                onSave={(text) => onUpdate({ introScreenHeader: text })}
                placeholder="Help us improve"
                className="font-medium text-sm"
                saveOnBlur
                clickToEdit
                compactIcon
                showEditIconOnHover
            />
            <EditableField
                name="intro-description"
                multiline
                value={appearance.introScreenDescription || ''}
                onSave={(text) => onUpdate({ introScreenDescription: text })}
                placeholder="Add a description (optional)"
                className="text-secondary text-xs"
                saveOnBlur
                clickToEdit
                compactIcon
                showEditIconOnHover
            />
            <EditableField
                name="intro-button-text"
                value={appearance.introScreenButtonText || ''}
                onSave={(text) => onUpdate({ introScreenButtonText: text })}
                placeholder="Get started"
                className="text-secondary text-xs"
                saveOnBlur
                clickToEdit
                compactIcon
                showEditIconOnHover
            />
        </ScreenEditorCard>
    )
}
