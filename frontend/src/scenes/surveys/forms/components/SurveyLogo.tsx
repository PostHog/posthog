import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconImage, IconPencil, IconTrash } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { Spinner } from 'lib/lemon-ui/Spinner'

import { surveyFormBuilderLogic } from '../surveyFormBuilderLogic'

export function SurveyLogo({ showCover }: { showCover: boolean }): JSX.Element {
    const { surveyForm, logoUploading } = useValues(surveyFormBuilderLogic)
    const { uploadImage, removeLogo } = useActions(surveyFormBuilderLogic)
    const fileInputRef = useRef<HTMLInputElement>(null)

    const hasImage = !!surveyForm.logoMediaId || !!surveyForm.logoUrl
    const imageSrc = surveyForm.logoMediaId ? `/uploaded_media/${surveyForm.logoMediaId}` : surveyForm.logoUrl

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>): void => {
        const file = e.target.files?.[0]
        if (file) {
            uploadImage(file, 'logo')
        }
        e.target.value = ''
    }

    return (
        <div className={`mx-auto max-w-4xl px-12${showCover ? ' -mt-12' : ' pt-6'}`}>
            <div className="group relative inline-flex items-center justify-center w-24 h-24 rounded-full border-2 border-border bg-bg-light overflow-hidden">
                {logoUploading ? (
                    <Spinner className="text-2xl" />
                ) : hasImage && imageSrc ? (
                    <img src={imageSrc} alt="Logo" className="w-full h-full object-cover" />
                ) : (
                    <IconImage className="text-4xl text-muted" />
                )}
                {!logoUploading && (
                    <div className="absolute inset-0 flex items-center justify-center rounded-full bg-overlay opacity-0 group-hover:opacity-100 transition-opacity">
                        <LemonMenu
                            items={[
                                {
                                    items: [
                                        {
                                            label: hasImage ? 'Change logo' : 'Upload logo',
                                            onClick: () => fileInputRef.current?.click(),
                                        },
                                        {
                                            label: 'Remove logo',
                                            icon: <IconTrash />,
                                            status: 'danger' as const,
                                            onClick: removeLogo,
                                        },
                                    ],
                                },
                            ]}
                            placement="bottom"
                        >
                            <LemonButton size="small" icon={<IconPencil />} type="secondary" className="bg-bg-light" />
                        </LemonMenu>
                    </div>
                )}
                <input ref={fileInputRef} type="file" accept="image/*" className="hidden" onChange={handleFileChange} />
            </div>
        </div>
    )
}
