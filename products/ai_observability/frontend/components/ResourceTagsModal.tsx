import { useActions, useValues, type BuiltLogic } from 'kea'

import { LemonBanner, LemonButton, LemonModal } from '@posthog/lemon-ui'

import { TagsInputSelect } from 'lib/components/TagsInputSelect'

import type { resourceTagsLogicType } from './resourceTagsLogic'

export function ResourceTagsModal({ logic }: { logic: BuiltLogic<resourceTagsLogicType> }): JSX.Element {
    const { isOpen, draft, saving, error } = useValues(logic)
    const { close, setDraft, save } = useActions(logic)
    return (
        <LemonModal
            isOpen={isOpen}
            onClose={saving ? undefined : close}
            title="Edit tags"
            footer={
                <>
                    <LemonButton type="secondary" onClick={close} disabledReason={saving ? 'Saving tags' : undefined}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" onClick={save} loading={saving} data-attr="aio-resource-tags-save">
                        Save
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-3">
                {error && <LemonBanner type="error">{error}</LemonBanner>}
                <TagsInputSelect
                    value={draft}
                    onChange={setDraft}
                    saving={saving}
                    disabled={saving}
                    placeholder="Add tags"
                    fullWidth
                />
            </div>
        </LemonModal>
    )
}
