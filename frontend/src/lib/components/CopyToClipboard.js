import React, { useRef } from 'react'
import { toast } from 'react-toastify'
import { Tooltip, Input } from 'antd'
import { CopyOutlined } from '@ant-design/icons'

export function CopyToClipboard({ url, ...props }) {
    const urlRef = useRef()

    function copyToClipboard() {
        urlRef.current.focus()
        urlRef.current.select()
        document.execCommand('copy')
        urlRef.current.blur()
        toast('Link copied!')
    }

    return (
        <Input
            type="text"
            ref={urlRef}
            value={url}
            suffix={
                <Tooltip title="Copy to Clipboard">
                    <CopyOutlined onClick={copyToClipboard} />
                </Tooltip>
            }
            {...props}
        />
    )
}
