import type { Meta, StoryObj } from '@storybook/react'

import { ByokModelPickerNotice, ByokModelPickerNoticeProps } from './ByokModelPickerNotice'
import { ModelPicker } from './ModelPicker'

const meta: Meta = {
    title: 'Scenes-App/AI observability/BYOK model picker notice',
}
export default meta

const render = (args: ByokModelPickerNoticeProps): JSX.Element => (
    <div className="w-full max-w-2xl">
        <ModelPicker
            model=""
            selectedProviderKeyId={null}
            onSelect={() => {}}
            groups={[]}
            footerLink={{ label: 'Add your own API keys', to: '#' }}
        />
        <ByokModelPickerNotice {...args} />
    </div>
)

export const NoProviderKeys: StoryObj<ByokModelPickerNoticeProps> = {
    render,
    args: { hasGroups: false, loading: false, loadFailed: false, onRetry: () => {} },
}

export const ModelsFailedToLoad: StoryObj<ByokModelPickerNoticeProps> = {
    render,
    args: { hasGroups: false, loading: false, loadFailed: true, onRetry: () => {} },
}
