import { kea, resetContext, getContext } from '../../src'

import React, { Component } from 'react'
import renderer from 'react-test-renderer'

class SampleComponent extends Component {
  render() {
    const { id, name, capitalizedName } = this.props
    const { updateName } = this.actions

    return (
      <div>
        <div className="id">{id}</div>
        <div className="name">{name}</div>
        <div className="capitalizedName">{capitalizedName}</div>
        <div className="updateName" onClick={updateName}>
          updateName
        </div>
      </div>
    )
  }
}

describe('snapshot', () => {
  beforeEach(() => {
    resetContext()
  })

  test('snapshots must match', () => {
    const { store } = getContext()

    const singletonLogic = kea({
      path: () => ['scenes', 'something'],
      actions: () => ({
        updateName: (name) => ({ name }),
      }),
      reducers: ({ actions }) => ({
        name: [
          'chirpy',
          {
            [actions.updateName]: (state, payload) => payload.name,
          },
        ],
      }),
      selectors: ({ selectors }) => ({
        capitalizedName: [
          () => [selectors.name],
          (name) => {
            return name
              .trim()
              .split(' ')
              .map((k) => `${k.charAt(0).toUpperCase()}${k.slice(1).toLowerCase()}`)
              .join(' ')
          },
        ],
      }),
    })

    const ConnectedComponent = singletonLogic(SampleComponent)

    const tree = renderer.create(<ConnectedComponent id={12} />).toJSON()

    expect(tree).toMatchSnapshot()
  })
})
