import { kea, resetContext, getContext } from '../../src'

import React, { Component } from 'react'
import { render, screen } from '@testing-library/react'

describe('selectors props', () => {
  beforeEach(() => {
    resetContext({ autoMount: true })
  })

  class BookDetail extends Component {
    render() {
      const { book, bookId } = this.props
      return <div data-testid={`book-${bookId}`}>{book}</div>
    }
  }

  test("selectors have access to the wrapped component's props", () => {
    const { store } = getContext()

    const books = {
      1: 'book1',
      2: 'book2',
    }

    const booksLogic = kea({
      reducers: {
        books: [books, {}],
      },
    })

    const bookDetailLogic = kea({
      key: (props) => props.bookId,
      selectors: ({ selectors }) => ({
        book: [() => [booksLogic.selectors.books, (_, props) => props.bookId], (books, bookId) => books[bookId]],
      }),
    })

    const ConnectedBookDetail = bookDetailLogic(BookDetail)

    render(
      <div className="playground-scene">
        <ConnectedBookDetail bookId={1} />
        <ConnectedBookDetail bookId={2} />
      </div>,
    )

    expect(screen.getByTestId('book-1')).toHaveTextContent('book1')
    expect(screen.getByTestId('book-2')).toHaveTextContent('book2')

    // only one of the components should be in the store, as only one has a reducer
    expect(Object.keys(store.getState().kea.logic).length).toEqual(1)
  })
})
