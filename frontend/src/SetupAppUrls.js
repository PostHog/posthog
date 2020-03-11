import React, { useState } from 'react'
import { useActions, useValues } from 'kea'
import api from './Api';

import { userLogic } from './userLogic'

const defaultValue = 'https://'

export default function SetupAppUrls () {
  const [saved, setSaved] = useState(false)
  const { user } = useValues(userLogic)
  const { updateUser } = useActions(userLogic)

  const [appUrls, setAppUrls] = useState(user.team.app_urls || [defaultValue])

  function addUrl () {
    setAppUrls(appUrls.concat([defaultValue]))
  }

  function removeUrl (index) {
    const newAppUrls = [...appUrls]
    newAppUrls.splice(index, 1)
    setAppUrls(newAppUrls)
  }

  function updateUrl (index, value) {
    const newAppUrls = [...appUrls]
    newAppUrls[index] = value
    setAppUrls(newAppUrls)
  }

  function onSubmit (e) {
    e.preventDefault();
    updateUser({ team: { app_urls: appUrls } })
  }

  return (
    <div>
      <label>What URLs will you be using PostHog on?</label>
      <form onSubmit={onSubmit}>
        {appUrls.map((url, index) => (
          <div key={index} style={{ marginBottom: 5 }}>
            <input
              value={url}
              onChange={(e) => updateUrl(index, e.target.value)}
              autoFocus={appUrls.count === 1 && appUrls[0] === defaultValue}
              style={{ display: 'inline-block', maxWidth: 400 }}
              type="url"
              className='form-control'
              placeholder={defaultValue}
            />
            {index > 0 ? <button className='btn btn-link' type="button" onClick={() => removeUrl(index)}>Remove</button> : null}
          </div>
        ))}
        <button className='btn btn-link' type="button" onClick={addUrl} style={{ padding: '5px 0', marginBottom: 15 }}>+ Add Another URL</button>
        <br />

        <button className='btn btn-success' type="submit">Save URLs</button>
        {saved && <span className='text-success' style={{ marginLeft: 10 }}>URLs saved.</span>}
      </form>
    </div>
  )
}
