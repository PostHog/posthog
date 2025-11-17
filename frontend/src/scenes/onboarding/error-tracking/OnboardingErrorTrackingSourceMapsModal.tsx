import { LemonModal } from '@posthog/lemon-ui'

import { SDK } from '~/types'

import { SourceMapsSDKInstructions } from './source-maps/SourceMapsSDKInstructionsMap'

export function SourceMapsInstructionsModal({
    isOpen,
    onClose,
    sdk,
}: {
    isOpen: boolean
    onClose: () => void
    sdk?: SDK
}): JSX.Element {
    const sdkInstructions = sdk?.key
        ? SourceMapsSDKInstructions[sdk.key as keyof typeof SourceMapsSDKInstructions]
        : undefined

    const InstructionComponent = sdkInstructions as (() => JSX.Element) | undefined

    return (
        <LemonModal isOpen={isOpen} onClose={onClose} simple title="">
            <div className="overflow-y-auto p-6">
                {InstructionComponent && (
                    <div className="space-y-4">
                        <h2 className="text-2xl font-bold">{sdk?.name}</h2>
                        <InstructionComponent />
                    </div>
                )}
            </div>
        </LemonModal>
    )
}
