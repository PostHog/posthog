import cohere


def aget_cohere_client() -> cohere.AsyncClientV2:
    return cohere.AsyncClientV2()


def get_cohere_client() -> cohere.ClientV2:
    return cohere.ClientV2()
