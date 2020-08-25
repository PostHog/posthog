import React, { useRef } from 'react'
import { toast } from 'react-toastify'
import { Tooltip, Input } from 'antd'
import { CopyOutlined } from '@ant-design/icons'

export function CopyToClipboard({ url, placeholder, addonBefore, addonAfter, ...props }) {
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
            placeholder={placeholder || 'nothing to show here'}
            disabled={!url}
            suffix={
                url ? (
                    <Tooltip title="Copy to Clipboard">
                        <CopyOutlined onClick={copyToClipboard} />
                    </Tooltip>
                ) : null
            }
            addonBefore={addonBefore}
            addonAfter={addonAfter}
            {...props}
        />
    )
}
