import React, { useState } from 'react'
import { useActions, useValues } from 'kea'
import api from './Api';

import { userLogic } from './userLogic'

export default function SetupAppUrls () {
  const [saved, setSaved] = useState(false)
  const { user } = useValues(userLogic)
  const { setUser } = useActions(userLogic)

  function addUrl () {
    user.team.app_urls.push('https://');
    setUser(user);
  }

  function removeUrl (index) {
    user.team.app_urls.splice(index, 1);
    setUser(user);
  }

  function updateUrl (index, value) {
    user.team.app_urls[index] = value;
    setUser(user);
  }

  function onSubmit (e) {
    e.preventDefault();
    api.update('api/user', {team: { app_urls: user.team.app_urls }}).then(response => {
      setSaved(true)
      user.team.app_urls = response.team.app_urls;
      setUser(user);
    })
  }

  const appUrls = user.team.app_urls || ['https://']

  return (
    <div>
      <label>What URLs will you be using PostHog on?</label>
      <form onSubmit={onSubmit}>
        {appUrls.map((url, index) => (
          <div key={index} style={{ marginBottom: 5 }}>
            <input
              defaultValue={url}
              onChange={(e) => updateUrl(index, e.target.value)}
              autoFocus
              style={{ display: 'inline-block', maxWidth: 400 }}
              type="url"
              className='form-control'
              name={`url${index}`}
              placeholder="https://...."
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
