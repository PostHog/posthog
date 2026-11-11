export type TransactionalEmailIdentity = {
    $email_template_id?: string
    $email_template_key?: string
}

export const SES_TEMPLATE_ID_TAG = 'ph_template_id'
export const SES_TEMPLATE_KEY_TAG = 'ph_template_key'

const SES_TAG_VALUE = /^[A-Za-z0-9_.@-]{1,256}$/

export const transactionalEmailIdentity = (
    config: { template_uuid?: unknown; template_key?: unknown } | undefined
): TransactionalEmailIdentity => ({
    ...(typeof config?.template_uuid === 'string' && config.template_uuid
        ? { $email_template_id: config.template_uuid }
        : {}),
    ...(typeof config?.template_key === 'string' && config.template_key
        ? { $email_template_key: config.template_key }
        : {}),
})

export const transactionalEmailIdentityTags = (
    config: { template_uuid?: unknown; template_key?: unknown } | undefined
): { Name: string; Value: string }[] => {
    const { $email_template_id: id, $email_template_key: key } = transactionalEmailIdentity(config)
    return [
        ...(id && SES_TAG_VALUE.test(id) ? [{ Name: SES_TEMPLATE_ID_TAG, Value: id }] : []),
        ...(key && SES_TAG_VALUE.test(key) ? [{ Name: SES_TEMPLATE_KEY_TAG, Value: key }] : []),
    ]
}

export const sentTransactionalEmailIdentity = (
    tags: Record<string, string[]> | undefined
): TransactionalEmailIdentity => {
    const id = tags?.[SES_TEMPLATE_ID_TAG]?.[0]
    const key = tags?.[SES_TEMPLATE_KEY_TAG]?.[0]
    return {
        ...(id ? { $email_template_id: id } : {}),
        ...(key ? { $email_template_key: key } : {}),
    }
}
