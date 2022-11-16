import { ChangeEvent, useState } from 'react'
import { IconUploadFile } from 'lib/components/icons'
import { LemonTag } from 'lib/components/LemonTag/LemonTag'
import { Spinner } from 'lib/components/Spinner/Spinner'

export interface LemonFileInputProps extends Pick<HTMLInputElement, 'multiple' | 'accept'> {
    value?: File[]
    onChange?: (newValue: File[]) => void
    // are the files currently being uploaded?
    loading?: boolean
}

export const LemonFileInput = ({
    value,
    onChange,
    multiple,
    loading,
    // e.g. '.json' or 'image/*'
    accept,
}: LemonFileInputProps): JSX.Element => {
    const [files, setFiles] = useState(value || ([] as File[]))

    const onInputChange = (e: ChangeEvent<HTMLInputElement>): void => {
        const eventFiles = e.target.files
        const filesArr = Array.prototype.slice.call(eventFiles)
        setFiles(multiple ? [...files, ...filesArr] : [filesArr[0]])
        onChange?.(files)
    }

    return (
        <>
            <div className={'flex flex-col gap-1'}>
                <label className="flex flow-row items-center gap-1 cursor-pointer">
                    <input
                        className={'hidden'}
                        type="file"
                        multiple={multiple}
                        accept={accept}
                        onChange={onInputChange}
                    />
                    <IconUploadFile /> Click or drag and drop to upload
                </label>
                <div className={'flex flex-row gap-2'}>
                    {files.map((x, i) => (
                        <LemonTag key={i} icon={loading ? <Spinner /> : undefined}>
                            {x.name}
                        </LemonTag>
                    ))}
                </div>
            </div>
        </>
    )
}
