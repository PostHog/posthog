import { Button, Upload } from 'antd'
import { UploadFile } from 'antd/lib/upload/interface'
import { IconUploadFile } from 'lib/lemon-ui/icons'

export function UploadField({
    value,
    onChange,
}: {
    value?: UploadFile | null
    onChange?: (file?: UploadFile | null) => void
}): JSX.Element {
    return (
        <Upload
            multiple={false}
            fileList={value?.size ? [value] : []}
            beforeUpload={(file) => {
                onChange?.(file)
                return false
            }}
            onRemove={() => {
                onChange?.(null)
                return false
            }}
            className="ph-ignore-input"
        >
            <Button icon={<IconUploadFile />}>Click to upload</Button>
        </Upload>
    )
}
