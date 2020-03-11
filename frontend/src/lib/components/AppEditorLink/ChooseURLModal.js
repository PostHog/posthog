import React, { useState, useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { Modal } from '../Modal';
import api from '../../api'
import { userLogic } from '../../../scenes/userLogic'
import { UrlRow } from './UrlRow'
import { appEditorUrl, defaultUrl } from './utils'

export function ChooseURLModal ({ actionId, dismissModal }) {
    const { user } = useValues(userLogic)
    const { setUser, loadUser, userUpdateRequest } = useActions(userLogic)
    const appUrls = user.team.app_urls

    const [newValue, setNewValue] = useState(defaultUrl)
    const [addingNew, setAddingNew] = useState(false)

    // We run this effect so that the URLs are the latest ones from the database.
    // Otherwise if you edit/add an URL, click to it and then click back, you will
    // see state urls (i.e. without the one you just added)
    useEffect(() => {
        loadUser()
    }, []) // run just once

    function saveUrl ({ index, value, callback }) {
        const newUrls = typeof index === 'undefined' ? appUrls.concat([value]) : appUrls.map((url, i) => i === index ? value : url)

        const willRedirect = appUrls.length === 0 && typeof index === 'undefined'

        api.update('api/user', { team: { app_urls: newUrls } }).then(user => {
            callback(newUrls)

            // Do not set the app urls when redirecting.
            // Doing so is bad UX as the screen will flash from the "add first url" dialog to
            // the "here are all the urls" dialog before the user is redirected away
            if (!willRedirect) {
                setUser(user)
            }
            if (!index) {
                setAddingNew(false)
            }
        })
    }

    function deleteUrl ({ index }) {
        const newUrls = appUrls.filter((v, i) => i !== index)
        userUpdateRequest({ team: { app_urls: newUrls } })
    }

    return (
        <Modal
            title={'On which domain do you want to create an action?'}
            footer={appUrls.length > 0 && !addingNew && <div style={{ flex: 1 }}><button className='btn btn-outline-secondary' style={{ flex: 1 }} onClick={() => setAddingNew(true)}>+ Add Another URL</button></div>}
            onDismiss={dismissModal}
        >
            {appUrls.length === 0 ? (
                <div>
                    <input value={newValue} onChange={e => setNewValue(e.target.value)} autoFocus style={{ maxWidth: 400 }} type="url" className='form-control' name='url' placeholder={defaultUrl} />
                    <br />
                    <button
                        onClick={() => saveUrl({ value: newValue, callback: () => { window.location.href = appEditorUrl(actionId, newValue) } })}
                        className='btn btn-success'
                        type="button"
                    >
                        Save URL & go
                    </button>
                </div>
            ) : (
                <ul className="list-group">
                    {appUrls.map((url, index) => (
                        <UrlRow
                            key={`${index},${url}`}
                            actionId={actionId}
                            url={url}
                            saveUrl={(value, callback) => saveUrl({ index, value, callback })}
                            deleteUrl={() => deleteUrl({ index })}
                        />
                    ))}
                    {addingNew ? (
                        <UrlRow
                            actionId={actionId}
                            url={defaultUrl}
                            saveUrl={(value, callback) => saveUrl({ value, callback })}
                            deleteUrl={() => setAddingNew(false)}
                        />
                    ) : null}
                </ul>
            )}
        </Modal>
    )
}
