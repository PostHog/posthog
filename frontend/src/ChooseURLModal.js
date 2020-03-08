import React, { useState, useCallback } from 'react';
import Modal from './Modal';
import api from './Api'

export function appEditorUrl (actionId, appUrl) {
  return '/api/user/redirect_to_site/' + (actionId ? '?actionId=' + actionId : '') + (appUrl ? `${actionId ? '&' : '?'}appUrl=${encodeURIComponent(appUrl)}` : '')
}

const defaultUrl = 'https://'

function UrlRow ({ actionId, url, saveUrl, deleteUrl }) {
  const [isEditing, setIsEditing] = useState(false)
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
          <button className='btn btn-primary' style={{ marginLeft: 5 }} onClick={() => { saveUrl(editedValue, () => { setIsEditing(false); setSavedValue(editedValue) }) }}>Save</button>
          <button className='btn btn-outline-secondary' style={{ marginLeft: 5 }} onClick={() => { setIsEditing(false); setEditedValue(savedValue || url || defaultUrl) }}>Cancel</button>
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
  function saveUrl ({ index, value, callback }) {
    const newUrls = typeof index === 'undefined' ? appUrls.concat([value]) : appUrls.map((url, i) => i === index ? value : url)

    api.update('api/user', { team: { app_urls: newUrls } }).then(() => {
      setAppUrls(newUrls)
      callback(newUrls)
    })
  }

  function deleteUrl ({ index }) {
    const newUrls = appUrls.filter((v, i) => i !== index)

    api.update('api/user', { team: { app_urls: newUrls } }).then(() => {
      setAppUrls(newUrls)
    })
  }

  return (
    <Modal title={'Which site shall we open?'} onDismiss={dismissModal}>
      <ul className="list-group">
        {appUrls.map((url, index) => (
          <UrlRow key={`${index},${url}`} actionId={actionId} url={url} saveUrl={(value, callback) => saveUrl({ index, value, callback })} deleteUrl={() => deleteUrl({ index })} />
        ))}
        <UrlRow key={`new_${appUrls.length}`} actionId={actionId} saveUrl={(value, callback) => saveUrl({ value, callback })} />
      </ul>
    </Modal>
  )
}
