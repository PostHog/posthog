function fetchReviews(productId) {
    if (!productId) {
        throw new Error('Missing product')
    }
    return [{ productId, stars: 5, text: 'Works as described' }]
}

export { fetchReviews };
//# debugId=8e45a01c-ff78-471a-87d3-ba56f7ab4c31
//# sourceMappingURL=reviews-nJfzDM_Q.mjs.map
