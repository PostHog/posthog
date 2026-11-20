"""English stop words for catalog search.

The list is the ``english`` text search config's list (``tsearch_data/english.stop`` in Postgres), so
the Python matching in metric search drops the same words that Postgres full-text search drops.
"""

ENGLISH_STOP_WORDS = frozenset(
    {
        *("i", "me", "my", "myself", "we", "our", "ours", "ourselves", "you", "your", "yours", "yourself"),
        *("yourselves", "he", "him", "his", "himself", "she", "her", "hers", "herself", "it", "its", "itself"),
        *("they", "them", "their", "theirs", "themselves", "what", "which", "who", "whom", "this", "that"),
        *("these", "those", "am", "is", "are", "was", "were", "be", "been", "being", "have", "has", "had"),
        *("having", "do", "does", "did", "doing", "a", "an", "the", "and", "but", "if", "or", "because", "as"),
        *("until", "while", "of", "at", "by", "for", "with", "about", "against", "between", "into", "through"),
        *("during", "before", "after", "above", "below", "to", "from", "up", "down", "in", "out", "on", "off"),
        *("over", "under", "again", "further", "then", "once", "here", "there", "when", "where", "why", "how"),
        *("all", "any", "both", "each", "few", "more", "most", "other", "some", "such", "no", "nor", "not"),
        *("only", "own", "same", "so", "than", "too", "very", "s", "t", "can", "will", "just", "don", "should"),
        "now",
    }
)

# Full-text search drops these too, but an embedding needs them: "users who did not convert" and
# "users who convert" ask for opposite metrics. "don" is what is left of "don't" after tokenizing.
NEGATION_WORDS = frozenset({"no", "nor", "not", "don"})
