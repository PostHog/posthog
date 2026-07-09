import clsx from 'clsx'
import { useState } from 'react'

import { LemonButton, LemonInput, LemonModal, LemonSegmentedButton } from '@posthog/lemon-ui'

import { capitalizeFirstLetter } from 'lib/utils/strings'

import {
    normalizeWordArtSize,
    normalizeWordArtStyle,
    WordArtSize,
    WORD_ART_PRESETS,
    WORD_ART_SIZES,
} from './wordArtPresets'
import { WordArtText } from './WordArtText'

const SIZE_OPTIONS = WORD_ART_SIZES.map((value) => ({
    value,
    label: value[0].toUpperCase(),
    tooltip: capitalizeFirstLetter(value),
    'data-attr': `word-art-size-${value}`,
}))

export function WordArtModal({
    onClose,
    onSave,
    initialText,
    initialStyle,
    initialSize,
}: {
    onClose: () => void
    onSave: (attrs: { text: string; style: string; size: WordArtSize }) => void
    initialText?: string
    initialStyle?: string
    initialSize?: string
}): JSX.Element {
    const [text, setText] = useState(initialText ?? '')
    const [style, setStyle] = useState(normalizeWordArtStyle(initialStyle))
    const [size, setSize] = useState<WordArtSize>(normalizeWordArtSize(initialSize))

    const trimmedText = text.trim()
    const previewText = trimmedText || 'Your text here'

    const save = (): void => {
        if (trimmedText) {
            onSave({ text: trimmedText, style, size })
        }
    }

    return (
        <LemonModal
            isOpen
            onClose={onClose}
            title="Word art"
            description="Pick a style. Yes, all of them are tasteful."
            width={640}
            forceAbovePopovers
            footer={
                <>
                    <LemonButton type="secondary" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={save}
                        disabledReason={!trimmedText ? 'Enter some text first' : undefined}
                    >
                        {initialText ? 'Update' : 'Insert'}
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                <div className="flex items-center gap-2">
                    <LemonInput
                        value={text}
                        onChange={setText}
                        placeholder="Your text here"
                        maxLength={100}
                        autoFocus
                        onPressEnter={save}
                        data-attr="word-art-text-input"
                        className="flex-1"
                    />
                    <LemonSegmentedButton value={size} onChange={setSize} options={SIZE_OPTIONS} size="small" />
                </div>
                <div className="grid grid-cols-3 gap-2">
                    {WORD_ART_PRESETS.map((preset) => (
                        <button
                            key={preset.id}
                            type="button"
                            title={preset.label}
                            data-attr={`word-art-style-${preset.id}`}
                            onClick={() => setStyle(preset.id)}
                            className={clsx(
                                'flex h-24 items-center justify-center overflow-hidden rounded border bg-white p-2',
                                style === preset.id
                                    ? 'border-accent ring-1 ring-accent'
                                    : 'border-primary hover:border-accent'
                            )}
                        >
                            <WordArtText text={previewText} style={preset.id} className="WordArt--preview" />
                        </button>
                    ))}
                </div>
            </div>
        </LemonModal>
    )
}
