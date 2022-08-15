import React from 'react'
import { Button, Upload } from 'antd'
import { UploadOutlined } from '@ant-design/icons'
import { UploadFile } from 'antd/lib/upload/interface'

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
            <Button icon={<UploadOutlined />}>Click to upload</Button>
        </Upload>
    )
}
