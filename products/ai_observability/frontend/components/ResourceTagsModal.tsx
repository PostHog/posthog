import { useActions, useValues, type BuiltLogic } from 'kea'

import { LemonBanner, LemonButton, LemonInputSelect, LemonModal } from '@posthog/lemon-ui'

import { tagsModel } from '~/models/tagsModel'

import type { resourceTagsLogicType } from './resourceTagsLogic'

export function ResourceTagsModal({ logic }: { logic: BuiltLogic<resourceTagsLogicType> }): JSX.Element {
    const { isOpen, draft, saving, error } = useValues(logic)
    const { close, setDraft, save } = useActions(logic)
    const { tags: availableTags } = useValues(tagsModel)
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
                <LemonInputSelect
                    mode="multiple"
                    value={draft}
                    onChange={setDraft}
                    options={availableTags.map((tag) => ({ key: tag, label: tag }))}
                    allowCustomValues
                    placeholder="Add tags"
                    disabled={saving}
                    fullWidth
                />
            </div>
        </LemonModal>
    )
}
