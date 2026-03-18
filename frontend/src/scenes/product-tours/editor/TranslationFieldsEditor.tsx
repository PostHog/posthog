import { useActions, useValues } from 'kea'

import { IconGlobe } from '@posthog/icons'
import { LemonInput, LemonTag } from '@posthog/lemon-ui'

import { productTourLogic } from '../productTourLogic'

export function TranslationFieldsEditor({ tourId }: { tourId: string }): JSX.Element | null {
    const { selectedStep, selectedLanguage } = useValues(productTourLogic({ id: tourId }))
    const { updateSelectedStep } = useActions(productTourLogic({ id: tourId }))

    if (!selectedStep) {
        return null
    }

    if (!selectedStep.buttons?.primary && !selectedStep.buttons?.secondary) {
        return null
    }

    return (
        <div className="border rounded overflow-hidden">
            <div className="flex items-center justify-start gap-2 px-3 py-2 bg-surface-primary border-b font-semibold">
                <span className="text-xs font-semibold uppercase tracking-wide text-muted">Translations</span>
                <LemonTag className="flex gap-2">
                    <IconGlobe /> {selectedLanguage}
                </LemonTag>
            </div>
            <div className="py-3 px-4">
                <div className="space-y-3">
                    {selectedStep.buttons?.primary && (
                        <div className="space-y-1">
                            <label className="text-xs font-medium">Primary button</label>
                            <LemonInput
                                value={selectedStep.buttons.primary.text}
                                onChange={(text) =>
                                    updateSelectedStep({
                                        buttons: {
                                            ...selectedStep.buttons,
                                            primary: { ...selectedStep.buttons!.primary!, text },
                                        },
                                    })
                                }
                                size="small"
                                fullWidth
                            />
                        </div>
                    )}

                    {selectedStep.buttons?.secondary && (
                        <div className="space-y-1">
                            <label className="text-xs font-medium">Secondary button</label>
                            <LemonInput
                                value={selectedStep.buttons.secondary.text}
                                onChange={(text) =>
                                    updateSelectedStep({
                                        buttons: {
                                            ...selectedStep.buttons,
                                            secondary: { ...selectedStep.buttons!.secondary!, text },
                                        },
                                    })
                                }
                                size="small"
                                fullWidth
                            />
                        </div>
                    )}

                    <p className="text-muted text-sm">To edit other settings, switch to your default language.</p>
                </div>
            </div>
        </div>
    )
}
