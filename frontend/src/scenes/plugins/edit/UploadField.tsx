import React from 'react'
import { Button, Upload } from 'antd'
import { UploadOutlined } from '@ant-design/icons'
import { UploadFile } from 'antd/es/upload/interface'

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
        >
            <Button icon={<UploadOutlined />}>Click to Upload</Button>
        </Upload>
    )
}
