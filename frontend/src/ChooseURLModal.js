import React, { useState, useCallback, useEffect } from 'react'
import Modal from './Modal';
import api from './Api'

export function appEditorUrl (actionId, appUrl) {
  return '/api/user/redirect_to_site/' + (actionId ? '?actionId=' + actionId : '') + (appUrl ? `${actionId ? '&' : '?'}appUrl=${encodeURIComponent(appUrl)}` : '')
}

const defaultUrl = 'https://'

function UrlRow ({ actionId, url, saveUrl, deleteUrl }) {
  const [isEditing, setIsEditing] = useState(url === defaultUrl)
  const [savedValue, setSavedValue] = useState(url || defaultUrl)
  const [editedValue, setEditedValue] = useState(url || defaultUrl)

  return (
    <li className="list-group-item">
      {isEditing ? (
        <div key='form' style={{ display: 'flex', width: '100%' }}>
          <input
            value={editedValue}
            onChange={(e) => setEditedValue(e.target.value)}
            autoFocus
            style={{ flex: '1' }}
            type="url"
            className='form-control'
            placeholder={defaultUrl}
          />
          <button className='btn btn-primary' style={{ marginLeft: 5 }} onClick={() => {
            if (editedValue === defaultUrl) {
              deleteUrl()
            } else {
              saveUrl(editedValue, () => {
                setIsEditing(false);
                setSavedValue(editedValue)
              })
            }
          }}>Save</button>
          <button className='btn btn-outline-secondary' style={{ marginLeft: 5 }} onClick={() => {
            if (url === defaultUrl) {
              deleteUrl()
            } else {
              setIsEditing(false)
              setEditedValue(savedValue || url || defaultUrl)
            }
          }}>Cancel</button>
        </div>
      ) : typeof url === 'undefined' ? (
        <div key='add-new'>
          <a href='#' onClick={e => {e.preventDefault(); setIsEditing(true)}}>+ Add Another URL</a>
        </div>
      ) : (
        <div key='list'>
          <div style={{ float: 'right' }}>
            <button className='no-style' onClick={() => setIsEditing(true)}>
              <i className='fi flaticon-edit text-primary' />
            </button>
            <button className='no-style text-danger' onClick={deleteUrl}>
              <i className='fi flaticon-basket' />
            </button>
          </div>
          <a href={appEditorUrl(actionId, editedValue)}>{editedValue}</a>
        </div>
      )}
    </li>
  )
}

export function ChooseURLModal ({ actionId, appUrls, setAppUrls, dismissModal }) {
  // We run this effect so that the URLs are the latest ones from the database.
  // Otherwise if you edit/add an URL, click to it and then click back, you will
  // see state urls (i.e. without the one you just added)
  useEffect(() => {
    api.get('api/user').then(response => {
      const freshAppUrls = response && response.team && response.team.app_urls

      if (freshAppUrls.join(',') !== appUrls.join(',')) {
        setAppUrls(freshAppUrls)
      }
    })
  }, []) // run just once

  function saveUrl ({ index, value, callback }) {
    const newUrls = typeof index === 'undefined' ? appUrls.concat([value]) : appUrls.map((url, i) => i === index ? value : url)

    const willRedirect = appUrls.length === 0 && typeof index === 'undefined'

    api.update('api/user', { team: { app_urls: newUrls } }).then(() => {
      callback(newUrls)

      // Do not set the app urls when redirecting.
      // Doing so is bad UX as the screen will flash from the "add first url" dialog to
      // the "here are all the urls" dialog before the user is redirected away
      if (!willRedirect) {
        setAppUrls(newUrls)
      }
    })
  }

  function deleteUrl ({ index }) {
    const newUrls = appUrls.filter((v, i) => i !== index)

    api.update('api/user', { team: { app_urls: newUrls } }).then(() => {
      setAppUrls(newUrls)
    })
  }

  function addUrl () {
    setAppUrls(appUrls.concat([defaultUrl]))
  }

  const [newValue, setNewValue] = useState(defaultUrl)

  return (
    <Modal
      title={'Which site shall we open?'}
      footer={appUrls.length > 0 && <div style={{ flex: 1 }}><a href='#' style={{ flex: 1 }} onClick={addUrl}>+ Add Another URL</a></div>}
      onDismiss={dismissModal}
    >
      {appUrls.length === 0 ? (
        <div>
          <label>What URL will you be using PostHog on?</label>
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
        </ul>
      )}
    </Modal>
  )
}
